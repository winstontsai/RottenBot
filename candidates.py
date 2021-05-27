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
		self.start = find_start(xmlentry.text, match.start())
		self.end = match.end()
		self.rtid = extract_rtid(xmlentry, match)


candidate_re = rt_re + r"[^.\n%]*?" + score_re + r".*?" + citation_re
# candidate_re2= r"[.\n>][^.\n]*?" + rt_re + r"[^.\n%]+?" + score_re + r".*?" + t_citeweb

def rt_url(movieid):
	return "https://www.rottentomatoes.com/" + movieid

def find_start(text, j):
	st = {'\n', '.', '>'}
	ind = next((i for i in range(j-1, -1, -1) if text[i] in st), None) + 1
	ind += (text[ind] == ' ')
	# if text[ind] == '\n':
	# 	return ind + 1
	# else:
	# 	return ind + 2
	return ind

def extract_rtid(xmlentry, match):
	"""
	Given the re.Match object which has identified a candidate, extracts the movieid.
	"""

	# Cite web template case
	if match.group('citeweb'):
		return match.group('rtid')
	# Cite Rotten Tomatoes template case
	elif match.group('citert'):
		d = parse_template(match.group('citert'))[1]
		return "m/" + d['id']
	# Rotten Tomatoes template case 
	elif match.group('rt'):
		d = parse_template(match.group('rt'))[1]

		if 'id' in d.keys():
			return d['id']
		if 1 in d.keys():
			return d[1]

		# Check for Wikidata property P1258
		page = Page(Site('en','wikipedia'), xmlentry.title)
		item = ItemPage.fromPage(page)
		item.get()
		if 'P1258' in item.claims:
			return item.claims['P1258'][0].getTarget()

	raise ValueError("Could not extract the Rotten Tomatoes ID from the page {}.".format(xmlentry.title))


def find_candidates(xmldump, pattern = candidate_re):
	"""
	Given an XmlDump, use pattern to
	find all pages in the dump which contain Rotten Tomatoes
	score info which might need editing.

	This is a generator function.
	"""
	gen = xmldump.parse()
	for entry in gen:
		m = re.search(pattern, entry.text)
		if m:
			#print(m.groupdict())
			yield Candidate(entry, m)


