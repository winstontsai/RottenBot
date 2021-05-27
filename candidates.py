# This module basically does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes url,
# and also finds the start of the sentence in which the rating info is contained.

import re

from pywikibot import Site, Page, ItemPage

from patterns import *



candidate_re = rt_re + r"[^.\n%]*?" + score_re + r".*?" + t_citeweb
# candidate_re2= r"[.\n>][^.\n]*?" + rt_re + r"[^.\n%]+?" + score_re + r".*?" + t_citeweb

def rt_url(movieid):
	return "https://www.rottentomatoes.com/" + movieid

def extract_rtid(xmlentry, match):
	"""
	Given the re.Match object which has identified a candidate, extracts the movieid.
	"""

	# Cite web case
	if match.group('rtid'):
		return match.group('rtid')
	elif match.group('citert'):
		d = parse_template(match.group('citert'))
		return "m/" + d['id']
	elif match.group('rt'):
		d = parse_template(match.group('rt'))

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




	return

def find_candidates(xmldump, pattern = candidate_re):
	"""
	Given an XmlDump, find all pages in the dump which contain Rotten Tomatoes
	score info which might need editing.

	This is a generator function. It yields pairs of the form
	(entry, m) where entry is the XmlEntry representing a Wikipedia page
	and m is the Match object that
	identified the page as a candidate for editing.
	"""
	gen = xmldump.parse()
	for entry in gen:
		m = re.search(pattern, entry.text)
		if m:
			yield (entry, m)


