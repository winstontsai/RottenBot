import re

from patterns import *


candidate_re = rt_re + r"[^.\n%]+?" + score_re + r".*?" + s_citeweb

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


