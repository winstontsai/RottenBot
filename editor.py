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

import pywikibot as pwb
import candidates
from patterns import *

class Edit:

	def __init__(self, title, old_prose, new_prose, old_citation, new_citation, handler, complete_rewrite = False):
		self.title = title
		self.old_prose = old_prose
		self.new_prose = new_prose
		self.old_citation = old_citation
		self.new_citation = new_citation
		self.complete_rewrite = complete_rewrite

		# Handler method for the edit.
		self.handler = handler

class Editor:

	def __init__(self, recruiter):
		self.recruiter = recruiter


	def compute_edits(self, user_input = True):
		"""
		Takes the candidates that the recruiter provides and computes
		the edits needed for each candidate.
		Yields these as Edit objects.
		Suspicious edits may either be yielded, or they may be manually
		implemented, depending on the user's input.

		Args:
			user_input: if True, suspicious edits will require user input
			to be handled. Otherwise suspicious edits will be ignored.
		"""

		# Suspect list of suspicious edits. Each suspect is a pair (Candidate, handler),
		# where handler is the appropriate method to deal with each suspect.
		# These user will handle these suspicious edits after all other
		# edits are yielded. 
		suspects = []

		for cand in self.recruiter.find_candidates():
			e = self._compute_edit(cand, suspects)
			if e:
				yield e
		for suspect, handler in suspects:
			if e := handler(suspect):
				yield e


	def _compute_edit(self, cand, suspect_list):
		if cand.prose[0] not in "[{'ABCDEFGHIJKLMNOPQRSTUVWXYZ":
			handler = Editor._suspicious_start_handler
		else:
			handler = Editor._replacement_handler

		d = cand.rt_data
		if not d:
			return None

		old_prose = cand.prose
		new_prose = cand.prose # used to build up the new prose


		# handle average rating		
		new_prose, k = re.subn(average_re, d['average']+'/10', new_prose)
		if k == 0:
			return Edit(cand.title, old_prose=old_prose, new_prose=full_replacement(cand, d),
				old_citation='', new_citation='',
				handler=handler, complete_rewrite=True)
		elif k > 1:
			handler = Editor._multiple_average_handler


		# handle review count
		if not (m := re.search(count_re, old_prose)):
			return Edit(cand.title, old_prose=old_prose, new_prose=full_replacement(cand, d),
				old_citation='', new_citation='',
				handler=handler, complete_rewrite=True)
		elif m.group().endswith("reviews"):
			repl = d['count'] + " reviews"
		else:
			repl = d['count'] + " critics"

		new_prose, k = re.subn(count_re, repl, new_prose)
		if k > 1:
			handler = Editor._multiple_count_handler

			
		# handle score
		new_prose = new_prose.replace(cand.score, d['score'] + '%')


		if new_prose != old_prose:
			return Edit(cand.title, old_prose=old_prose, new_prose=new_prose,
				old_citation='', new_citation='',
				handler=handler, complete_rewrite=False)

		return None

	@staticmethod
	def _replacement_handler(edit):
		page = pwb.Page(pwb.Site('en', 'wikipedia'), edit.title)
		page.text = page.text.replace(edit.old_prose, edit.new_prose)
		page.text = page.text.replace(edit.old_citation, edit.new_citation)
		page.save()

	@staticmethod
	def _suspicious_start_handler(edit):
		print("Suspicious start index for [[{}]] detected.".format(edit.title))
		print("Here is the old prose:")
		print(edit.old_prose)
		print()
		print("Here is the new prose:")
		print(edit.new_prose)
		print()

		user_input = input("Select an option: [r]eplace old prose with new prose, open [b]rowser for manual editing, [s]kip, or [q]uit.")
		while user_input not in "rbsq":
			user_input = input("Please select an option: [r]eplace, open [b]rowser for manual editing, [s]kip, or [q]uit.")

		if user_input == 'r':
			Editor._replacement_handler(edit)
		elif user_input == 'b':
			webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), edit.title).full_url())
			input("Press Enter when finished in browser.")
		elif user_input == 's':
			print("Skipping edit for [[{}]].".format(edit.title))
		elif user_input == 'q':
			print("Quitting program.")
			quit()

	@staticmethod
	def _multiple_average_handler(edit):
		print("multiple_average_handler")

	@staticmethod
	def _multiple_count_handler(edit):
		print("multiple_count_handler")


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
	rec = candidates.Recruiter(filename, cand_res)
	ed = Editor(rec)
	with shelve.open("storage/{}-edits-list".format(Path(filename).stem), flag = 'n') as db:
		for e in ed.compute_edits():
			db[e.title] = e
	t1 = time.perf_counter()
	print("TIME ELAPSED =", t1-t0, file = sys.stderr)








