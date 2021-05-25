import re

from patterns import *


candidate_re = rt_re + r"[^.\n%]+?" + score_re + r".+?" + s_citeweb

def find_candidates(xmldump, pattern = candidate_re):
	"""
	Given an XmlDump, find all pages in the dump which contain Rotten Tomatoes
	score info which might need editing.
	"""
	gen = xmldump.parse()
	for entry in gen:
		m = re.search(pattern, entry.text)
		if m:
			yield (entry, m)









