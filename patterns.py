# This module defines some regexes/patterns that will be used, along with some
# related helper functions.

def rt_url(movieid):
	return "https://www.rottentomatoes.com/" + movieid

def alternates(l):
	return f'(?:{"|".join(l)})'

def construct_redirects(l):
	"""
	Constructs the part of a regular expression which
	allows different options corresponding to the redirects listed in l.
	For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
	use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
	"""
	redirects = [f"[{x[0] + x[0].lower()}]{x[1:]}" for x in l]
	return alternates(redirects)


def parse_template(template):
	"""
	Takes the text of a template (the stuff between "{{"" and ""}}"") and
	returns the template's name and a dict of the key-value pairs.
	Unnamed parameters are given the integer keys 1, 2, 3, etc, in order.
	"""
	d = dict()
	counter = 1
	pieces = [x.strip() for x in template.split('|')]
	template_name = pieces[0]
	for piece in pieces[1:]:
		j = piece.find('=')
		if j == -1:
			d[counter] = piece
			counter += 1
		else:
			key = piece[:j].rstrip()
			value = piece[j + 1:].lstrip()
			d[key] = value
	return (template_name, d)

def construct_template(name, d):
	s = name
	for key,value in d:
		if type(key) == int:
			s += f" |{value}"
		else:
			s += f" |{key}={value}"
	return s

rt_re = r"[rR]otten [tT]omatoes"
score_re = r"(?P<score>([0-9]|[1-9][0-9]|100)(%| percent))"
count_re = r"(?P<count>([5-9]|[1-9][0-9]|[1-9][0-9][0-9]) ((critical )?reviews|(surveyed )?critics))"
average_re = r"(?P<average>([0-9]|10)(\.\d{1,2})?(/| out of )(10|ten))"

url_re = r"rottentomatoes.com/(?P<rt_id>m/[-a-z0-9_]+)"

# Regular expressions for the source/citation, where we will find the
# Rotten Tomatoes URL for the movie.

# for the {{Cite web}} and {{Cite news}} and {{Citation}} templates
citeweb_redirects = [
    "Cite web", "Cite-web", "Citeweb", "Cite Web",
    "Cite news", "Citenews", "Cite-news", "Cite News",
    "Citation", "Cite",
    ]
t_citeweb = fr"{{{{(?P<citeweb>{construct_redirects(citeweb_redirects)}.+?{url_re}.*?)}}}}"

citenews_redirects = []

# for the {{Cite Rotten Tomatoes}} template
citert_redirects = ["Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"]
t_citert = fr"{{{{(?P<citert>{construct_redirects(citert_redirects)}.+?)}}}}"

# for the {{Rotten Tomatoes}} template
rt_redirects = [ "Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
				"Rotten tomatoes", "Rotten", "Rottentomatoes.com"]
t_rt = fr"{{{{(?P<rt>{construct_redirects(rt_redirects)}.*?)}}}}"

# For any reference which includes the rotten tomatoes url pattern.
# Not necessarily a template
# This is a generalization of the Cite web, Cite news, and Citation templates.
# Can handle "abnormal" cases where a template is not used.
t_other = fr'(?P<citeweb>.+?{url_re}.*?)'

# for inline citations
t_alternates = alternates([t_other,t_citert,t_rt])
citation_re = fr'(?P<citation><ref( +name *= *(?P<refname>[^<>]+?))? *>.*?{t_alternates}.*?</ref *>)'

# for list-defined references
ldref_re = r'(?P<ldref><ref +name *= *(?P<ldrefname>[^<>]+?) */>)'

cand_re1 = rt_re + r"[^.\n<>]*?" + score_re + r"[^\n<>]*?" + citation_re
cand_re2 = score_re + r"[^.\n<>]*?" + rt_re + r"[^\n<>]*?" + citation_re
cand_re3 = rt_re + r"[^.\n<>]*?" + score_re + r"[^\n<>]*?" + ldref_re
cand_re4 = score_re + r"[^.\n<>]*?" + rt_re + r"[^\n<>]*?" + ldref_re

cand_re5 = rt_re + r"[^.\n<>]*?" + score_re + r"[^\n<>]*?" + alternates([citation_re,ldref_re])
cand_re6 = score_re + r"[^.\n<>]*?" + rt_re + r"[^\n<>]*?" + alternates([citation_re,ldref_re])

# cand_re1 = fr"{rt_re}[^.\n>]*?{score_re}[^\n>]*?{citation_re}"
# cand_re2 = fr"{score_re}[^.\n>]*?{rt_re}[^\n>]*?{citation_re}"
cand_res = [cand_re5, cand_re6]



if __name__ == "__main__":
	print(parse_template("cite web | title= Meadowland Reviews | url= https://www.metacritic.com/movie/meadowland | website= [[Metacritic]] |publisher= [[CBS Interactive]] | access-date= February 22, 2020 "))

