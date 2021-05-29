# This module is takes Candidates,
# determines whether or not it should be edited,
# and if so produces the new text.

import re
import sys
import urllib
import webbrowser
import shelve
import time
from pathlib import Path

from pywikibot import Site, Page, xmlreader

import candidates
from patterns import *

class Edit:

	def __init__(self, title, old_prose, new_prose, old_citation, new_citation):
		self.title = title
		self.old_prose = old_prose
		self.new_prose = new_prose
		self.old_citation = old_citation
		self.new_citation = new_citation

class Editor:

	def __init__(self, xmlfile):
		self.filename = xmlfile

		# Suspect list of suspicoius edits. Each suspect is a pair (Candidate, reason),
		# where reason is the reason this suspect was added to the list
		self.suspects = list()

	def compute_edits(self, user_input = True):
		for cand in candidates.find_candidates(xmlreader.XmlDump(self.filename)):
			e = self._compute_edit(cand)
			if e:
				yield e


	def _compute_edit(self, cand):
		d = cand.rt_data
		if not d:
			return None

		old_prose = cand.prose
		new_prose = cand.prose # used to build up the new prose


		# handle average rating		
		new_prose, k = re.subn(average_re, d['average']+'/10', new_prose)
		if k == 0:
			return Edit(cand.title, old_prose, full_replacement(cand, d), '', '')
		elif k > 1:
			self.suspects.append((cand, "multiple average replacement"))


		# handle review count
		m = re.search(count_re, old_prose)
		if not m:
			return Edit(cand.title, old_prose, full_replacement(cand, d), '', '')
		if m.group().endswith("reviews"):
			repl = d['count'] + " reviews"
		else:
			repl = d['count'] + " critics"

		new_prose, k = re.subn(count_re, repl, new_prose)
		if k > 1:
			self.suspects.append((cand, "multiple count replacement"))
		# handle score
		new_prose = new_prose.replace(cand.score, d['score'] + '%')

		# check for edge cases
		if cand.suspicious_start():
			self.suspects.append((cand, "start index"))
			print("Suspicious start index for {} detected. First character is '{}'.".format(cand.title, cand.text[cand.start]))
			# user_input = input("Either [s]kip this article or open in [b]rowser for manual editing.\nAny other input will [e]xit the program.")
			# if user_input == 's':
			# 	print("Skipping article {}.".format(cand.title))
			# 	pass
			# elif user_input == 'b':
			# 	webbrowser.open(Page(Site('en', 'wikipedia'), cand.title).full_url())
			# else:
			# 	print("Exiting program.")
			# 	quit()

			# return False

		if new_prose != old_prose:
			return Edit(cand.title, old_prose, new_prose, '', '')

		return None



def full_replacement(cand, d):
	s = "On review aggregator [[Rotten Tomatoes]], the film holds an approval rating \
of {}% based on {} reviews, with an average rating of {}/10.".format(d['score'], d['count'], d['average'])
	if d['consensus']:
		s += " The website's critical consensus reads, \"{}\"".format(d['consensus'])

	# add citation
	# s += "<ref>{{{{Cite Rotten Tomatoes |id={} |type=movie |title={} |access-date={}}}}}</ref>".format(cand.rt_id[2:], d['title'], d['accessDate'])

	return s




if __name__ == "__main__":
	t0 = time.perf_counter()
	filename = sys.argv[1]
	ed = Editor(filename)
	with shelve.open("storage/{}-edits-list".format(Path(filename).stem), flag = 'n') as db:
		for e in ed.compute_edits():
			db[e.title] = e
	t1 = time.perf_counter()
	print("TIME ELAPSED =", t1-t0, file = sys.stderr)








