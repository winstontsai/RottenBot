import time
import sys
import shelve

import pywikibot

import scraper
import candidates
import editor
from editor import *
from patterns import *



filename = sys.argv[1]

rec = candidates.Recruiter(filename, cand_res)
ed = editor.Editor(rec)

with shelve.open(filename, flag = 'r') as db:
	for key, value in db.items():
		print(key, value)

