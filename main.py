import time
import sys
import shelve
import argparse

import pywikibot as pwb

import scraper
import candidates
import editor
from editor import *
from patterns import *



filename = sys.argv[1]

rec = candidates.Recruiter(filename, cand_res)
ed = editor.Editor(rec)

for edit in ed.compute_edits():
	edit.handler(edit)

