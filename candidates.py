# This module basically does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes url,
# and also finds the start of the sentence in which the rating info is contained.

import re

from patterns import *


candidate_re = rt_re + r"[^.\n%]*?" + score_re + r".*?" + t_citeweb
# candidate_re2= r"[.\n>][^.\n]*?" + rt_re + r"[^.\n%]+?" + score_re + r".*?" + t_citeweb

def rt_url(movieid):
	return "https://www.rottentomatoes.com/m/iron_man" + movieid

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


