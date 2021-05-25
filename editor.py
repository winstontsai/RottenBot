import pywikibot
from pywikibot import pagegenerators

site = pywikibot.Site('en', 'wikipedia')
page = pywikibot.Page(site, "Transformers (film)")
print(page.text)



def find_rtscore(s):
	"""
	Given the Wikipedia page text of a film's page, attempts to find the
	Rotten Tomatoes score and url of the film.

	Arguments:
		s: A string of the page text to look in.

	Returns:
		An empty list if the Rotten Tomatoes score is absent,
		otherwise a list of the following form:
			[score percentage, rating count, average rating, url]
	"""
	regex = r"\s\[\[[rR]otten [tT]omatoes\]\]\D+(\d{1,3}%)\D+(\d{1,3})\D+(\d+(?:\.\d+)?)(?:/| out of )10"
	p = re.compile(regex)
	