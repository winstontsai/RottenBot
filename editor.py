# This module is takes Candidates,
# determines whether or not it should be edited,
# and if so produces the new text.

import re
import sys
import urllib
import webbrowser

from pywikibot import Site, Page

import scraper
from patterns import *


def full_replacement(cand, d):
	s = "On review aggregator [[Rotten Tomatoes]], the film holds an approval rating \
of {}% based on {} reviews, with an average rating of {}/10.".format(d['score'], d['count'], d['average'])
	if d['consensus']:
		s += " The website's critical consensus reads, \"{}\"".format(d['consensus'])

	# add citation
	s += "<ref>{{{{Cite Rotten Tomatoes |id={} |type=movie |title={} |access-date={}}}}}</ref>".format(cand.rt_id[2:], d['title'], d['accessDate'])

	return s


def try_to_update(cand):
	d = cand.rt_data
	if not d:
		return False

	old_text = cand.text[cand.start : cand.end]
	new_text = old_text # we build up the replacement


	# handle average rating		
	new_text, k = re.subn(average_re, d['average']+'/10', new_text)
	if k == 0:
		return full_replacement(cand, d)


	# handle review count
	m = re.search(count_re, old_text)
	if not m:
		return full_replacement(cand, d)
	if m.group().endswith("reviews"):
		repl = d['count'] + " reviews"
	else:
		repl = d['count'] + " critics"
	new_text, k = re.subn(count_re, repl, new_text)
	if k == 0:
		return full_replacement(cand, d)

	# handle score
	new_text = new_text.replace(cand.score, d['score'] + '%')

	# check for edge cases
	if cand.suspicious_start():
		print("Suspicious start index for {} detected. First character is '{}'.".format(cand.title, cand.text[cand.start]))
		user_input = input("Please either [s]kip this article or open it in [b]rowser for manual editing. Any other input will exit the program.")
		if user_input == 's':
			print("Skipping article {}.".format(cand.title))
			pass
		elif user_input == 'b':
			webbrowser.open(Page(Site('en', 'wikipedia'), cand.title).full_url())
		else:
			print("Exiting program.")
			quit()

		return False

	if new_text != old_text:
		return new_text

	return False






if __name__ == "__main__":
	pass








