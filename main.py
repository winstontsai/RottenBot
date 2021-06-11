import time
import sys
import shelve
import pickle
import json
import argparse

import pywikibot as pwb

import candidates
import editor
import patterns



# function for shelve command
def store_edits(args):
	r = candidates.Recruiter(args.xmlfile, patterns.cand_res)
	e = editor.Editor(r)

	# with shelve.open(args.file) as db:
	# 	for edit in e.compute_edits():
	# 		db[edit.title] = edit

	with open(args.file, 'wb') as f:
		for edit in e.compute_edits():
			pickle.dump(edit, f)
			

def store_candidates(args):
	r = candidates.Recruiter(args.xmlfile,  patterns.cand_res)

	# with shelve.open(args.file) as db:
	# 	for cand in r.find_candidates(patterns.cand_res):
	# 		db[cand.title] = cand

	with open(args.file, 'wb') as f:
		for cand in r.find_candidates(patterns.cand_res):
			pickle.dump(cand, f)


# function for upload command
def upload_edits(args):
	print("upload_edits({})".format(args))






if __name__ == '__main__':
	parser = argparse.ArgumentParser(description = 'Bot to help edit Rotten Toatoes film ratings on the English Wikipedia.',
		epilog="""Use '-h' after a subcommand to read about a specific subcommand.
See 'https://github.com/winstontsai/RottenBot' for more info about this bot.""",
		formatter_class=argparse.RawDescriptionHelpFormatter,)
	parser.add_argument('-v', '--verbose', action='count', default=1,
		help='increase verbosity level')	

	subparsers = parser.add_subparsers(title='commands',
		dest='command',
		required=True,
		metavar='command',
		help='available commands',)

	# parser for shelving
	parser_s = subparsers.add_parser('store', aliases=['shelve'],
		help='store edits in a file')
	parser_s.set_defaults(func=store_edits)
	parser_s.add_argument('-c', '--candidates',
		dest='func', action='store_const', const=store_candidates,
		help='instead of edits, store the titles and Rotten Tomatoes ids')
	parser_s.add_argument('xmlfile', help="file containing the XML dump of Wikipedia pages to work on")
	parser_s.add_argument('file', help='file in which to store edits')
	

	# parser for uploading
	parser_u = subparsers.add_parser('upload', aliases=['up'],
		help='upload edits to the live wiki')
	parser_u.set_defaults(func=upload_edits)
	parser_u.add_argument('file', help='name of the file from which edits will be uploaded')
	parser_u.add_argument('-d', '--dryrun', action='store_true',
		help='no edits will actually be made to the live wiki')

	args = parser.parse_args()

	t0=time.perf_counter()
	args.func(args)
	t1=time.perf_counter()
	print("TIME ELAPSED =", t1-t0, file = sys.stderr)



