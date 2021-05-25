import urllib.request
import re
import json
import time

from scraper import *

import pywikibot
from pywikibot import pagegenerators
from pywikibot.xmlreader import XmlDump


class CandidatePage:
	pass


def construct_redirects_re(l):
	"""
	Constructs the part of a regular expression which
	allows different options corresponding to the redirects listed in l.
	For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
	use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
	"""
	redirects = ["[{}]{}".format(x[0] + x[0].lower(),x[1:]) for x in l]
	return "(?:{})".format("|".join(redirects))


rt_re = r"(?:\[\[)?[rR]otten [tT]omatoes(?:\[\[)?"
score_re = r"(?P<score>[0-9]|[1-9][0-9]|100)(?:%| percent)"
count_re = r"(?P<count>\d{1,3})"
count2_re = r"(?P<count>[5-9]|[1-9][0-9]|[1-9][0-9][0-9])"
average_re = r"(?P<average>\d{1,2}(?:\.\d{1,2})?)(?:/| out of )10"
fill = r"[^\d.\n]+?"


# Regular expressions for the source/citation, where we will find the
# Rotten Tomatoes URL for the movie.
s_citeweb = r"<ref>{{(?P<citeweb>[cC]ite web.+?rottentomatoes.com/m/[-a-z0-9_]+.*?)}}</ref>"

s_citert = r"<ref>{{(?P<citert>" + construct_redirects_re([
	"Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"
	]) +  ".+?)}}</ref>"

s_rt = "<ref>{{(?P<rt>" + construct_redirects_re([
		"Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
		"Rotten tomatoes", "Rotten", "Rottentomatoes.com"
	]) + ".+?)}}</ref>"

s_ldref = r"<ref name=(.+?)/>"

source_re = "(?:{})".format("|".join([s_rt, s_citeweb, s_citert]))




if __name__ == "__main__":
	site = pywikibot.Site('en', 'wikipedia')
	site.login()

	total = 0
	matched = 0

	gen = XmlDump('xmldumps/2010s-films.xml').parse()

	t0 = time.perf_counter()

	for page in gen:
		total += 1

		p = rt_re + r"[^.\n%]+?" + score_re + r".+?" + s_citeweb
		m = re.search(p, page.text)
		if m:
			print("MATCH {}".format(page.title))
			print(m.group(0))
			#print(json.dumps(m.groupdict(), indent = 4))
			matched += 1

	t1 = time.perf_counter()
	print("MATCHED / TOTAL = {} / {}".format(matched, total))
	print("TOTAL TIME ELAPSED =", t1-t0)
	print("REGEX USED:", p)







