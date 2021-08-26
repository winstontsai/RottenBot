import time
import sys
import os
import pickle
import json
import argparse
import logging.handlers
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

import pywikibot as pwb

import candidates
import wikieditor
import patterns
################################################################################

def store_candidates(args):
    data = candidates.find_candidates(args.file1, get_user_input=args.interactive)
    with open(args.file2, 'wb') as f:
        pickle.dump(list(data), f)

def store_edits(args):
    if args.file1.endswith('.cands'):
        with open(args.file1, 'rb') as f:
            cands = pickle.load(f)         
    else:
        cands = candidates.find_candidates(args.file1, get_user_input=args.interactive)

    edits = wikieditor.compute_edits(cands, get_user_input=args.interactive)
    with open(args.file2, 'wb') as f:
        pickle.dump(list(edits), f)


# function for upload command
def upload_edits(args):
    print("upload_edits({})".format(args))

def print_data(args):
    with open(args.file, 'rb') as f:
        data = pickle.load(f)
    print(type(data))
    print(data)

def listpages(args):
    site = pwb.Site('en','wikipedia')
    for catname in args.catname:
        cat = pwb.Category(pwb.Page(site, catname, ns=14))
        for x in cat.articles(recurse=True, namespaces=0):
            print(x.title())


def get_args():
    parser = argparse.ArgumentParser(description = 'Bot to help edit Rotten Toatoes film ratings on the English Wikipedia.',
        epilog="""Use '-h' after a subcommand to read about a specific subcommand.
See 'https://github.com/winstontsai/RottenBot' for source code and more info.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,)
    parser.add_argument('-v', '--verbose', action='count', default=1,
        help='Increase verbosity level.')    

    subparsers = parser.add_subparsers(title='commands',
        required=True,
        metavar='command',)

    # parser for shelving
    parser_store = subparsers.add_parser('store',
        help = 'Store edits in a file.')
    parser_store.set_defaults(func=store_edits)
    parser_store.add_argument('-c', '--candidates',
        dest='func', action='store_const', const=store_candidates,
        help='store candidates instead of edits')
    parser_store.add_argument('file1', help="The XML dump of Wikipedia pages to work on.")
    parser_store.add_argument('file2', help='The file in which to store edits.')
    parser_store.add_argument('-i', '--interactive', action='store_true',
        help='In interactive mode, the user will be asked for their input for certain articles.')
    

    # parser for uploading
    parser_upload = subparsers.add_parser('upload',
        help='Upload edits from a file to the live wiki.')
    parser_upload.set_defaults(func=upload_edits)
    parser_upload.add_argument('file', help='File from which edits will be uploaded.')
    parser_upload.add_argument('-d', '--dryrun', action='store_true',
        help='No edits will actually be made to the live wiki.')

    # parser for printing stored data
    parser_print = subparsers.add_parser('print',
        help='Print the pickled data from a file.')
    parser_print.set_defaults(func=print_data)
    parser_print.add_argument('file', help = 'File in which the data is stored.')

    # parser for listing articles in a category
    parser_list = subparsers.add_parser('listpages',
        help='List (recursively) all articles in one or more categories.')
    parser_list.set_defaults(func=listpages)
    parser_list.add_argument('catname', help='Category name.', nargs='+')

    return parser.parse_args()


def main():
    # handle logging setup
    os.makedirs("logs/", exist_ok=True)

    root_logger = logging.getLogger()
    print_logger = logging.getLogger('print_logger')

    should_roll = os.path.isfile("logs/rottenbot.log")
    file_handler = logging.handlers.RotatingFileHandler(
        filename = "logs/rottenbot.log",
        backupCount = 9)
    formatter = logging.Formatter('%(asctime)s %(name)s %(funcName)s [%(levelname)s]: %(message)s')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    if should_roll:
        file_handler.doRollover()

    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(message)s')
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    print_logger.addHandler(stream_handler)
    print_logger.setLevel(logging.INFO)
    print_logger.propagate = False

    # install_mp_handler(print_logger)


    # START PROGRAM
    logger.info("COMMAND '{}'".format(' '.join(sys.argv)))
    t0 = time.perf_counter()

    args = get_args()
    try:
        args.func(args)
    except SystemExit:
        pass

    t1 = time.perf_counter()
    logger.info("TIME ELAPSED = {}".format(t1 - t0))
    print_logger.info("TIME ELAPSED = {}".format(t1 - t0))


if __name__ == '__main__':
    main()






