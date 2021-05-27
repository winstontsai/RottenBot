# Defines the regexes/patterns that will be used.

def make_opt(s):
	return "(?:{})?".format(s)

def construct_redirects(l):
	"""
	Constructs the part of a regular expression which
	allows different options corresponding to the redirects listed in l.
	For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
	use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
	"""
	redirects = ["[{}]{}".format(x[0] + x[0].lower(),x[1:]) for x in l]
	return "(?:{})".format("|".join(redirects))


def parse_template(template):
	"""
	Takes the text of a template (the stuff between "{{"" and ""}}"") and
	returns a dict of the key-value pairs.
	Unnamed parameters are given the keys 1, 2, 3, etc, in order.
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

rt_re = r"[rR]otten [tT]omatoes"
score_re = r"(?P<score>[0-9]|[1-9][0-9]|100)(?:%| percent)"
count_re = r"(?P<count>\d{1,3})"
count_re2 = r"(?P<count>[5-9]|[1-9][0-9]|[1-9][0-9][0-9])"
average_re = r"(?P<average>\d{1,2}(?:\.\d{1,2})?)(?:/| out of )10"
average_re2 = r"(?P<average>(?:[0-9]|10)(?:\.\d{1,2})?)(?:/| out of )10"
fill = r"[^\d.\n]+?"


url_re = r"rottentomatoes.com/(?P<rtid>m/[-a-z0-9_]+)"

# Regular expressions for the source/citation, where we will find the
# Rotten Tomatoes URL for the movie.

# for the {{cite-web}} template
citeweb_redirects = ["Cite web", "Cite-web", "Citeweb", "Cite Web"]
t_citeweb = r"<ref>{{(?P<citeweb>" + construct_redirects(citeweb_redirects) + ".+?" + url_re + ".*?)}}</ref>"


# for the {{Cite Rotten Tomatoes}} template
citert_redirects = ["Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"]
t_citert = r"<ref>{{(?P<citert>" + construct_redirects(citert_redirects) +  ".+?)}}</ref>"


# for the {{Rotten Tomatoes}} template
rt_redirects = [ "Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
				"Rotten tomatoes", "Rotten", "Rottentomatoes.com"]
t_rt = "<ref>{{(?P<rt>" + construct_redirects(rt_redirects) + ".+?)}}</ref>"

t_ldref = r"<ref name=(.+?)/>"

citation_re = "(?P<citation>{})".format("|".join([t_citeweb, t_citert, t_rt]))

res = [ rt_re + fill + score_re + fill + count_re + make_opt(fill+average_re), 
		rt_re + fill + score_re + fill + average_re + make_opt(fill+count_re),
		rt_re + fill + count_re + fill + score_re + make_opt(fill+average_re),
		score_re + fill + rt_re + fill + count_re + make_opt(fill+average_re),
		score_re + fill + average_re + fill + rt_re + make_opt(fill+count_re),
		score_re + fill + count_re + fill + rt_re + make_opt(fill+average_re),
		rt_re + fill + score_re,
		score_re + fill + rt_re
	]

res_with_source = [x + ".+?" + citation_re for x in res]


if __name__ == "__main__":
	print(parse_template("cite web | title= Meadowland Reviews | url= https://www.metacritic.com/movie/meadowland | website= [[Metacritic]] |publisher= [[CBS Interactive]] | access-date= February 22, 2020 "))

