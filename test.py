#scikit-learn must be at version <= 0.17
import logging
import os
import argparse
import numpy
import random
import time
import json

import torch
import torch.utils.data as data

from models import select_net
from time_util import time_format
from MedicalDataset import MedicalDataset

def parse_args():
	parser = argparse.ArgumentParser()
	path_args_group = parser.add_mutually_exclusive_group(required=True)
	path_args_group.add_argument('-t', dest='test_data_path',
		type = argparse.FileType("r", encoding="utf-8"),
		help = 'Txt file listing directory paths containing DICOM '
			   'files to be tested (one path per line).')
	path_args_group.add_argument('--series-paths', nargs="+",
		help = 'Paths to directories of DICOM series containing DICOM files '
			   'to be tested.')
	parser.add_argument('-m', dest='model_file', type = str, required = True,
		help = 'Name of the trained model file.')
	parser.add_argument('-sl', dest='slices', type = int, default = 10,
		help = 'Number of central slices considered by the trained model.')
	parser.add_argument('-3d', dest='tridim', action = 'store_true',
		help = 'Use if the trained model used tridimensional convolution.')
	parser.add_argument('--no-other', dest='no_other', action = 'store_true',
		help = 'If specified, "Other" class is not considered.')
	parser.add_argument('--net', dest='net', type = str, default = 'resnet18',
		help = 'Network architecture to be used.')
	parser.add_argument('-d', '--debug', action="store_true",
		help="Enable debug logging")
	return parser.parse_args()

def fix_random_seeds():
	torch.backends.cudnn.deterministic = True
	random.seed(1)
	torch.manual_seed(1)
	torch.cuda.manual_seed(1)
	numpy.random.seed(1)

if __name__ == '__main__':
	args = parse_args()

	if args.test_data_path:
		# Read list of directory paths from TXT file
		test_data_path = [line.rstrip("\n") for line in
						  args.test_data_path.readlines()]
	else:
		test_data_path = args.series_paths

	model_file = args.model_file
	n_slices = args.slices
	tridim = args.tridim
	consider_other_class = not args.no_other
	architecture = args.net
	if args.debug:
		logging.basicConfig(format="%(asctime)s [%(levelname)-8s] %(message)s",
							level=logging.DEBUG)

	assert(architecture in ['resnet18', 'alexnet', 'vgg', 'squeezenet', 'mobilenet'])

	fix_random_seeds()
	
	test_set = MedicalDataset(
		test_data_path, min_slices = n_slices,
		consider_other_class = consider_other_class, test = True,
		debug=args.debug)
	test_loader = data.DataLoader(test_set, num_workers = 8, pin_memory = True)
	#test_loader = data.DataLoader(test_set, pin_memory = True)
	
	n_test_files = test_set.__len__()
	classes = ['FLAIR', 'T1', 'T1c', 'T2', 'OTHER'] #train_set.classes

	net = select_net(architecture, n_slices, tridim, consider_other_class)

	if torch.cuda.is_available():
		net = net.cuda()

	start_time = time.time()
		
	#test
	net.load_state_dict(torch.load(os.path.join('models', model_file), map_location=torch.device('cpu')))
	net.eval()
	correct = 0
	total = 0
	correct_per_class = [0] * len(classes)
	total_per_class = [0] * len(classes)
	actual_classes = []
	predicted_classes = []
	wrong_predictions = []

	results_all = {}
	with torch.no_grad():
		for i, (pixel_data, label, path) in enumerate(test_loader):
			label_as_num = label.numpy()[0]
			if tridim:
				pixel_data = pixel_data.view(-1, 1, 10, 200, 200)

			outputs = net(pixel_data.cpu())
			_, predicted = torch.max(outputs.data, 1)

			total += label.size(0)
			correct += (predicted == label.cpu()).sum().item()
			total_per_class[label_as_num] += label.size(0)
			correct_per_class[label_as_num] += (predicted == label.cpu()).sum().item()
			
			actual_classes.append(classes[label_as_num])
			predicted_classes.append(classes[predicted.cpu().numpy()[0]])
			predicted_label = classes[predicted.cpu().numpy()[0]]

			# Actual script output to stdout
			results_all[path[0]] = {"prediction": predicted_label}
			logging.debug(results_all[path[0]])
			
			if predicted != label.cpu():
				wrong_predictions.append((path[0], classes[label.numpy()[0]], classes[predicted.cpu().numpy()[0]]))
				
			logging.debug('Tested %s of %s files', i + 1, n_test_files)

	# Actual script output to stdout
	print(json.dumps(results_all))

	#time
	end_time = time.time()
	elapsed_time = time_format(end_time - start_time)
	logging.debug('Testing elapsed time: %s', elapsed_time)

