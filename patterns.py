# This module defines some reusable regexes/patterns, and some helper functions.
################################################################################
import re
################################################################################
def pattern_count(pattern, string, flags=0):
    return sum(1 for x in re.finditer(pattern, string, flags))

def alternates(l):
    return f'(?:{"|".join(l)})'

def template_re(name):
    """
    Returns regex matching a the specified template.
    Assumes no nested templates.
    """
    return fr'{{{{{name} *(?:\|.*?)?}}}}'

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
    Takes the text of a template and
    returns the template's name and a dict of the key-value pairs.
    Unnamed parameters are given the integer keys 1, 2, 3, etc, in order.
    """
    d, counter = dict(), 1
    pieces = [x.strip() for x in template.strip('{}').split('|')]
    for piece in pieces[1:]:
        if (j := piece.find('=')) == -1:
            d[str(counter)] = piece
            counter += 1
        else:
            d[piece[:j].rstrip()] = piece[j+1:].lstrip()
    return (pieces[0], d)

def construct_template(name, d):
    positional = ''
    named = ''
    for k, v in sorted(d.items()):
        if re.fullmatch(r"[1-9][0-9]*", k):
            positional += f"|{v}"
    for k, v in d.items():
        if not re.fullmatch(r"[1-9][0-9]*", k):
            named += f"|{k}={v}"
    return '{{' + name + positional + named + '}}'

rt_re = r"[rR]otten [tT]omatoes"
score_re = r"\b(?P<score>[0-9]|[1-9][0-9]|100)(?:%| percent)"
average_re = r"\b(?P<average>(?:[0-9]|10)(?:\.\d{1,2})?(?:/| out of )(?:10|ten))"

ones = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
tens = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
numword_re = alternates([fr"{alternates(tens)}([ -]{alternates(ones)})?"] + teens + ones[4:])
count_re = fr"\b(?P<count>[5-9]|[1-9][0-9]|[1-9][0-9][0-9]|{numword_re}) (?P<count_term>(critic(al)? )?review(er)?s|(surveyed )?critics)"

url_re = r"rottentomatoes.com/(?P<rt_id>m/[-a-z0-9_]+)"

# for the {{Cite web}} and {{Cite news}} and {{Citation}} templates
# citeweb_redirects = [
#     "Cite web", "Cite-web", "Citeweb", "Cite Web",
#     "Cite news", "Citenews", "Cite-news", "Cite News",
#     "Citation", "Cite",
#     ]
# t_citeweb = fr"(?P<citeweb>{{{{{construct_redirects(citeweb_redirects)}.+?{url_re}.*?}}}})"

# This will be used to match any reference which includes the RT url pattern.
# This is a generalization of the Cite web, Cite news, and Citation templates.
# Can handle a lot of edge cases, such as where a template is not used.
t_other = fr'(?P<citeweb>{url_re})'

# for the {{Cite Rotten Tomatoes}} template
citert_redirects = ["Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"]
t_citert = fr"(?P<citert>{template_re(construct_redirects(citert_redirects))})"

# for the {{Rotten Tomatoes}} template
rt_redirects = [ "Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
                "Rotten tomatoes", "Rotten", "Rottentomatoes.com"]
t_rt = fr"(?P<rt>{template_re(construct_redirects(rt_redirects))})"

# for the {{Rotten Tomatoes prose}} template
rtprose_redirects = [
    'Rotten Tomatoes prose',
    'RT',
    'RT prose', 
]
t_rtprose = fr"(?P<rtprose>{template_re(construct_redirects(rtprose_redirects))})"

# for the {{As of}} template
asof_redirects = ["As of", "Asof"]
t_asof = fr"(?P<asof>{template_re(construct_redirects(asof_redirects))})"

t_alternates = alternates([t_other,t_citert,t_rt])

citation_re = fr'(?P<citation><ref( +name *= *"?(?P<refname>[^>]+?)"?)? *>((?!<ref).)*?{t_alternates}((?!<ref).)*</ref *>)'

# for list-defined references. 
# ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>[^>]+?)"? */>)'

# matches zero or more consecutive references (not necessarily for RT), use re.DOTALL
anyrefs_re = r'(<ref( +name *= *[^>]+?)? *>((?!<ref).)*?</ref *>|<ref +name *= *[^>]+? */>)*'

# matches a bulleted list
# used to find the External Links section
# list_re = r'([*][^\n]+\n)+'

if __name__ == "__main__":
    print(numword_re)

