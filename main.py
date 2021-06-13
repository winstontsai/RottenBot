import time
import sys
import os
import pickle
import json
import argparse
import logging
import logging.handlers

import pywikibot as pwb

import candidates
import editor
import patterns



def store_edits(args):
	r = candidates.Recruiter(args.xmlfile, patterns.cand_res)
	e = editor.Editor(r)

	with open(args.file, 'wb') as f:
		for edit in e.compute_edits():
			pickle.dump(edit, f)
			

def store_candidates(args):
	r = candidates.Recruiter(args.xmlfile,  patterns.cand_res)

	with open(args.file, 'wb') as f:
		for cand in r.find_candidates():
			pickle.dump(cand, f)


# function for upload command
def upload_edits(args):
	print("upload_edits({})".format(args))



def print_data(args):
	s = []
	with open(args.file, 'rb') as f:
		while True:
			try:
				d = vars(pickle.load(f))
				s.append(json.dumps(d, indent = 4))
			except EOFError:
				break
	print("\n".join(s))



def get_args():
	parser = argparse.ArgumentParser(description = 'Bot to help edit Rotten Toatoes film ratings on the English Wikipedia.',
		epilog="""Use '-h' after a subcommand to read about a specific subcommand.
See 'https://github.com/winstontsai/RottenBot' for source code and more info.""",
		formatter_class=argparse.RawDescriptionHelpFormatter,)
	parser.add_argument('-v', '--verbose', action='count', default=1,
		help='increase verbosity level')	

	subparsers = parser.add_subparsers(title='commands',
		dest='command',
		required=True,
		metavar='command',
		help='available commands',)

	# parser for shelving
	parser_s = subparsers.add_parser('store',
		help='store edits in a file')
	parser_s.set_defaults(func=store_edits)
	parser_s.add_argument('-c', '--candidates',
		dest='func', action='store_const', const=store_candidates,
		help='store candidates instead of edits')
	parser_s.add_argument('xmlfile', help="file containing the XML dump of Wikipedia pages to work on")
	parser_s.add_argument('file', help='file in which to store edits')
	

	# parser for uploading
	parser_u = subparsers.add_parser('upload',
		help='upload edits from a file to the live wiki')
	parser_u.set_defaults(func=upload_edits)
	parser_u.add_argument('file', help='name of the file from which edits will be uploaded')
	parser_u.add_argument('-d', '--dryrun', action='store_true',
		help='no edits will actually be made to the live wiki')


	# parser for printing stored data
	parser_r = subparsers.add_parser('print',
		help='print the edits stored in a file')
	parser_r.set_defaults(func=print_data)
	parser_r.add_argument('file', help = 'file in which the data is stored')

	return parser.parse_args()




if __name__ == '__main__':
	# logging.basicConfig(
	# 	filename = 'logs/rottenbot.log',
	# 	filemode = 'a',
	# 	format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
	# 	level = logging.INFO
	# 	)
	should_roll = os.path.isfile("logs/rottenbot.log")

	logger = logging.getLogger()
	formatter = logging.Formatter('%(name)s %(asctime)s %(threadName)s %(funcName)s [%(levelname)s]: %(message)s')


	should_roll = os.path.isfile("logs/rottenbot.log")
	file_handler = logging.handlers.RotatingFileHandler(
		filename = "logs/rottenbot.log",
		backupCount = 20)
	file_handler.setFormatter(formatter)
	file_handler.setLevel(logging.DEBUG)
	if should_roll:
		file_handler.doRollover()

	stream_handler = logging.StreamHandler(sys.stdout)
	stream_handler.setLevel(logging.INFO)

	logger.addHandler(file_handler)
	logger.addHandler(stream_handler)
	logger.setLevel(logging.DEBUG)


	# START PROGRAM
	logging.info("COMMAND '{}'".format(' '.join(sys.argv)))

	t0 = time.perf_counter()
	args = get_args()
	args.func(args)
	t1 = time.perf_counter()

	logging.info("TIME ELAPSED = {}".format(t1 - t0))




