# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.

import re
import sys
import urllib
import shelve

import pywikibot as pwb

from patterns import *
import scraper


class Candidate:
	"""
	Holds the info we'll need for a candidate page to be edited.
	"""

	def __init__(self, xmlentry, match):
		self.title = xmlentry.title
		self.id = xmlentry.id
		self.text = xmlentry.text
		self.score = match.group('score')
		self.start = self._find_start(xmlentry.text, match.start())
		self.end = match.end()
		# citation text
		self.citation = match.group('citation')
		# prose text
		self.prose = xmlentry.text[self.start : match.start('citation')] 
		self.rt_id = self._extract_rt_id(match)
		self.rt_data = self._rt_data(match)

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


	def suspicious_start(self):
		return self.text[self.start] not in "[{'ABCDEFGHIJKLMNOPQRSTUVWXYZ"

	def p1258(self):
		"""
		Returns Wikidata property P1258 if it exists, otherwise returns None.
		"""
		page = pwb.Page(pwb.Site('en','wikipedia'), self.title)
		item = pwb.ItemPage.fromPage(page)
		item.get()
		if 'P1258' in item.claims:
			return item.claims['P1258'][0].getTarget()
		return None

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
			if p := self.p1258():
				return p

		raise ValueError("Could not find the Rotten Tomatoes ID for [[{}]].".format(self.title))

	def _rt_data(self, match):
		d = None
		try:
			url = rt_url(self.rt_id)
			d = scraper.get_rt_rating(url)
		except urllib.error.HTTPError:
			print("Problem getting Rotten Tomatoes data for [[{}]].\nNow looking for Wikidata property P1258.".format(self.title),
				file = sys.stderr)
			if p := self.p1258():
				self.rt_id = p
				print("Found Wikidata property P1258: {}.".format(self.rt_id), file=sys.stderr)
				d = scraper.get_rt_rating(rt_url(self.rt_id))
			else:
				print("Wikidata property P1258 does not exist for [[{}]].".format(self.title), file=sys.stderr)
			
			# else: # worst case, still need to test if this is really needed
			# 	try:
			# 		url = googlesearch.lucky(entry.title + " site:rottentomatoes.com")
			# 		rt_id = url.split('rottentomatoes.com/')[1]
			# 		d = scraper.get_rt_rating(rt_url(rt_id))
			# 	except Exception:
			# 		print("There was a problem retrieving data from Rotten Tomatoes for the page {}.".format{cand.title},
			# 			file = sys.stderr)
			# 		return False
		return d

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
		for entry in pwb.xmlreader.XmlDump(self.filename).parse():
			total += 1
			for p in self.patterns:
				if m := re.search(p, entry.text):
					count += 1
					yield Candidate(entry, m)
		print("CANDIDATES / TOTAL = {} / {}".format(count, total), file=sys.stderr)






if __name__ == "__main__":
	r = Recruiter("xmldumps/soundofnoise.xml", cand_res)
	for x in r.find_candidates:
		print(x)














