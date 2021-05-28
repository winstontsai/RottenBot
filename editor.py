# This module is takes Candidates from the candidates.py module and
# determines whether or not it should be edited.
# If so, it produces an Edit object which
# contains the relevant page, the old text to be replaced, and the replacement text.

import re
import sys
import urllib

from pywikibot import Site, Page, ItemPage

import scraper
from patterns import *


def rt_url(movieid):
	return "https://www.rottentomatoes.com/" + movieid


def try_to_update(cand):
	try:
		url = rt_url(cand.rtid)
		d = scraper.get_rt_rating(url)
	except urllib.error.HTTPError:
		print("""Problem getting Rotten Tomatoes data from article {}.
			Now checking for Wikidata property P1258.""".format(url),
			file = sys.stderr)
		page = Page(Site('en','wikipedia'), xmlentry.title)
		item = ItemPage.fromPage(page)
		item.get()
		if 'P1258' in item.claims:
			print("Found Wikidata property P1258.", file=sys.stderr)
			cand.rtid = item.claims['P1258'][0].getTarget()
			d = scraper.get_rt_rating(rt_url(cand.rtid))
		else:
			print("Could not find Wikidata property P1258.", file=sys.stderr)
			return False
		# else: # worst case, still need to test if this is really needed
		# 	try:
		# 		url = googlesearch.lucky(entry.title + " site:rottentomatoes.com")
		# 		rtid = url.split('rottentomatoes.com/')[1]
		# 		d = scraper.get_rt_rating(rt_url(rtid))
		# 	except Exception:
		# 		print("There was a problem retrieving data from Rotten Tomatoes for the page {}.".format{cand.title},
		# 			file = sys.stderr)
		# 		return False
	if d is None:
		return False



	rating_text = cand.text[cand.start: cand.end]


def construct_replacement():
	pass



if __name__ == "__main__":
	pass