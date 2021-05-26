# Defines the regexes/patterns that will be used.

def make_opt(s):
	return "(?:{})?".format(s)

def construct_redirects_re(l):
	"""
	Constructs the part of a regular expression which
	allows different options corresponding to the redirects listed in l.
	For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
	use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
	"""
	redirects = ["[{}]{}".format(x[0] + x[0].lower(),x[1:]) for x in l]
	return "(?:{})".format("|".join(redirects))

rt_re = r"[rR]otten [tT]omatoes"
score_re = r"(?P<score>[0-9]|[1-9][0-9]|100)(?:%| percent)"
count_re = r"(?P<count>\d{1,3})"
count2_re = r"(?P<count>[5-9]|[1-9][0-9]|[1-9][0-9][0-9])"
average_re = r"(?P<average>\d{1,2}(?:\.\d{1,2})?)(?:/| out of )10"
fill = r"[^\d.\n]+?"


url_re = r"rottentomatoes.com/m/(?P<movieid>[-a-z0-9_]+)"

# Regular expressions for the source/citation, where we will find the
# Rotten Tomatoes URL for the movie.

# for the {{cite-web}} template
t_citeweb = r"<ref>{{(?P<citeweb>[cC]ite web.+?" + url_re + "/?[ |].+?)}}</ref>"


# for the {{Cite Rotten Tomatoes}} template
t_citert = r"<ref>{{(?P<citert>" + construct_redirects_re([
	"Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"
	]) +  ".+?)}}</ref>"


# for the {{Rotten Tomatoes}} template
t_rt = "<ref>{{(?P<rt>" + construct_redirects_re([
		"Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
		"Rotten tomatoes", "Rotten", "Rottentomatoes.com"
	]) + ".+?)}}</ref>"

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

