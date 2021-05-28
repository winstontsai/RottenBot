# This module basically does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes url,
# and also finds the start of the sentence in which the rating info is contained.

import re

from pywikibot import Site, Page, ItemPage

from patterns import *


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
		self.rtid = extract_rtid(xmlentry, match)

	def _find_start(self, text, j):
		"""
		This function is supposed to find the index of the beginning of
		the sentence containing the Rotten Tomatoes rating info.

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
		return ind + (text[ind] == ' ')


def extract_rtid(xmlentry, match):
	"""
	Given the re.Match object which has identified a candidate, extracts the movieid.
	"""

	# Cite web template case
	if match.group('citeweb'):
		return match.group('rtid')

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
		page = Page(Site('en','wikipedia'), xmlentry.title)
		item = ItemPage.fromPage(page)
		item.get()
		if 'P1258' in item.claims:
			return item.claims['P1258'][0].getTarget()

	raise ValueError("Could not extract the Rotten Tomatoes ID from the page {}.".format(xmlentry.title))


def find_candidates(xmldump):
	"""
	Given an XmlDump, find all pages in the dump which contain Rotten Tomatoes
	score info which might need editing.

	This is a generator function.
	"""
	candidate_re1 = rt_re + r"[^.\n]*?" + score_re + r"[^\n]*?" + citation_re
	candidate_re2 = score_re + r"[^.\n]*?" + rt_re + r"[^\n]*?" + citation_re
	
	gen = xmldump.parse()
	for entry in gen:
		m = re.search(candidate_re1, entry.text)
		if not m:
			m = re.search(candidate_re2, entry.text)

		if m:
			yield Candidate(entry, m)



