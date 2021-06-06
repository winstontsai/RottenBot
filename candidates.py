# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.

import re
import sys
import urllib
import webbrowser

import googlesearch

import pywikibot as pwb
from pywikibot.xmlreader import XmlDump

from patterns import *
import scraper




class Candidate:
	"""
	Holds the info we'll need for a candidate page to be edited.
	"""

	def __init__(self, xmlentry, match):
		self.title = xmlentry.title
		self.id = xmlentry.id
		self._p1258 = -1
		self.text = xmlentry.text
		self.score = match.group('score')
		self.start = self._find_start(xmlentry.text, match.start())
		# self.end = match.end()
		# citation text
		self.citation = match.group('citation')
		# prose text
		self.prose = xmlentry.text[self.start : match.start('citation')] 
		self.rt_id = self._extract_rt_id(match)
		self.rt_data = self._rt_data(match)


	@property
	def p1258(self):
		if self._p1258 == -1:
			page = pwb.Page(pwb.Site('en','wikipedia'), self.title)
			item = pwb.ItemPage.fromPage(page)
			item.get()
			if 'P1258' in item.claims:
				self._p1258 = item.claims['P1258'][0].getTarget()
			else:
				self._p1258 = None
		return self._p1258

	def _find_start(self, text, j):
		"""
		This function is supposed to find the index of the beginning of
		the sentence containing the Rotten Tomatoes rating info.

		NOTE: There are edge cases where the index returned by this function
		is in fact NOT the start of the desired sentence (see suspicious_start).
		In these cases the bot operator will be asked for input.

		Args:
			text: the text of the page
			j: the start index of the re.Match object
		"""
		italics = False
		for i in range(j - 1, -1, -1):
			c = text[i]
			if c in "\n>":
				ind = i + 1
				break
			elif c == "." and not italics:
				ind = i + 1
				break
			elif c == "'" == text[i + 1]:
				italics = not italics

		ind += (text[ind] == ' ')

		return ind
	

	def _extract_rt_id(self, match):
		"""
		Given the re.Match object which has identified a candidate, extracts the movieid.
		"""

		# Cite web template case
		if match.group('citeweb'):
			return match.group('rt_id')

		# Cite Rotten Tomatoes template case
		if match.group('citert'):
			d = parse_template(match.group('citert'))[1]
			return "m/" + d['id']

		# Rotten Tomatoes template case 
		if match.group('rt'):
			d = parse_template(match.group('rt'))[1]
			if 'id' in d.keys():
				return ("" if d['id'].startswith('m/') else "m/") + d['id'] 
			if 1 in d.keys():
				return ("" if d[1].startswith('m/') else "m/") + d[1]

			# Check for Wikidata property P1258
			if p := self._p1258():
				return p

		raise ValueError("Could not find the Rotten Tomatoes ID for [[{}]].".format(self.title))

	def _rt_data_try(self, movieid, func, *args):
		"""
		Tries to return the RT data from rt_url(movieid),
		and executes func on a urllib.errorr.HTTPError.
		"""
		try:
			return scraper.get_rt_rating(rt_url(movieid))
		except urllib.error.HTTPError:
			return func(*args)

	def _rt_data_bad_first_try(self):
		print("Problem retrieving Rotten Tomatoes data for [[{}]] with id {}.".format(self.title, self.rt_id),
			file = sys.stderr)
		print("Checking for Wikidata property P1258...", file=sys.stderr)
		if self.p1258:
			print("Wikidata property P1258 exists: {}.".format(self.p1258),
				file = sys.stderr)
			return self._rt_data_try(self.p1258, self._rt_data_bad_p1258_try)
		else:
			print("Wikidata property P1258 does not exist.", file=sys.stderr)
			return self._ask_for_option()

	def _rt_data_bad_p1258_try(self):
		print("Problem getting Rotten Tomatoes data for [[{}]].".format(self.title),
			file=sys.stderr)
		return self._ask_for_option()

	def _ask_for_option(self):
		url = googlesearch.lucky(self.title + " site:rottentomatoes.com")
		print("_ask_for_option", file=sys.stderr)
		movieid = url.split('rottentomatoes.com/')[1]
		prompt = """Please select an option:
	1) use suggested id {}
	2) open the suggested RT page and [[{}]] in the browser
	3) enter id manually
	4) skip this article
	5) quit the program
Your selecton: """.format(movieid, self.title)
		while (user_input := input(prompt)) not in "134":
			if user_input == '2':
				webbrowser.open(rt_url(movieid))
				webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), self.title).full_url())
				input("Press Enter when finished in browser.")

			x = lambda: print("Problem retrieving data from Rotten Tomatoes for [[{}]].".format(self.title))
			if user_input == '1':
				return self._rt_data_try(movieid, x)
			elif user_input == '4':
				return print("Skipping article [[{}]].".format(self.title))
			elif user_input == '5':
				print("Quitting program.")
				quit()
			elif user_input == '3':
				newid = input("Enter id here: ")
				return self._rt_data_try(newid, x)

	def _rt_data(self, match):
		print(self.title, flush=True)
		return self._rt_data_try(self.rt_id, self._rt_data_bad_first_try)


	def _find_citation(self):
		pass


class Recruiter:
	def __init__(self, xmlfile, patterns):
		self.filename = xmlfile
		self.patterns = patterns

	def find_candidates(self):
		"""
		Given an XmlDump, yields all pages (as a Candidate) in the dump
		which match at least one pattern in patterns.
		"""
		total, count = 0, 0
		for entry in XmlDump(self.filename).parse():
			total += 1
			for p in self.patterns:
				if m := re.search(p, entry.text):
					count += 1
					yield Candidate(entry, m)
					#break
		print("CANDIDATES / TOTAL = {} / {}".format(count, total))






if __name__ == "__main__":
	pass














