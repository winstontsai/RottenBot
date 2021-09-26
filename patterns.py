# This module defines some reusable regexes/patterns, and some helper functions.
################################################################################
import regex as re
################################################################################
def pattern_count(pattern, text, flags=0):
    return sum(1 for x in re.finditer(pattern, text, flags))

def find_pattern(pattern, text, start=0, end=None, flags=0):
    if end is None:
        end = len(text)
    pattern = re.compile(pattern, flags)
    if m := pattern.search(text, start, end):
        return m.start()
    return -1

def rfind_pattern(pattern, text, start=0, end=None, flags=0):
    if end == None:
        end = len(text)
    pattern = re.compile(pattern, flags=flags|re.REVERSE)
    if m := pattern.search(text, start, end):
        return m.start()
    return -1

def index_pattern(pattern, text, start=0, end=None, flags=0):
    i = find_pattern(pattern, text, start, end, flags)
    if i == -1:
        raise ValueError('substring not found')
    return i

def rindex_pattern(pattern, text, start=0, end=None, flags=0):
    i = rfind_pattern(pattern, text, start, end, flags)
    if i == -1:
        raise ValueError('substring not found')
    return i

def paragraph_span(span, text):
    """
    Find span of the paragraph that contains a span.
    """
    i, j = span[0], span[1]
    start = rfind_pattern(r'\n(?:\n|==)', text, 0, i)
    if start == -1:
        start = 0
    elif text[start+1] == '\n':
        start += 2
    else:
        start = re.compile(r'\n').search(text, start+3).end()
    end = index_pattern(r'\n(?:\n|==)', text, j)
    return (start, end)

def is_subspan(x, y):
    """
    Return True if x is a subspan of y.
    """
    return y[0]<=x[0] and x[1]<=y[1]

##############################################################################
# Helper functions for making regular expressions
##############################################################################
def alternates(l):
    return f'(?:{"|".join(l)})'

def template_pattern(name, disambiguator = ''):
    """
    Returns regex matching the specified template.
    Assumes no nested templates.
    """
    disambiguator = str(disambiguator) # used to prevent duplicate group names
    z = ''.join(x for x in name if x.isalpha())[:20] + str(len(name)) + disambiguator
    t = r'(?P<template_' + z + r'>{{(?:[^}{]|(?&template_' + z + r'))*}})'
    return fr'{{{{\s*{name}\s*(?:\|(?:[^}}{{]|{t})*)?}}}}'

def construct_redirects(l):
    """
    Constructs the part of a regular expression which
    allows different options corresponding to the redirects listed in l.
    For example, if we want to match both "Rotten Tomatoes" and "RottenTomatoes",
    use this function with l = ["Rotten Tomatoes", "RottenTomatoes"]
    """
    redirects = [fr"[{x[0].upper() + x[0].lower()}]{x[1:]}" for x in l]
    return alternates(redirects)

##############################################################################
# Helper functions for templates
##############################################################################
def parse_template(template):
    """
    Takes the text of a template and
    returns the template's name and a dict of the key-value pairs.
    Unnamed parameters are given the integer keys 1, 2, 3, etc, in order.
    """
    d, counter = dict(), 1
    pieces = [x.strip() for x in template.strip('{}').split('|')]
    for piece in pieces[1:]:
        param, equals, value = piece.partition('=')
        if equals:
            d[param.rstrip()] = value.lstrip()
        else:
            d[str(counter)] = param
            counter += 1
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

def rtdata_template(*args, **kwargs):
    for i, arg in enumerate(args, start=1):
        kwargs[str(i)] = arg
    return construct_template('RT data', kwargs)

##############################################################################
# Regular expressions
##############################################################################

rt_re = r"\b(?P<rot>[rR]otten ?[tT]omatoe?s)\b"

ones = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
tens = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
# 5 <= x <= 99
numword_re1 = alternates([fr"{alternates(tens)}(?:[ -]{alternates(ones)})?"]+teens+ones[4:])
# 0 <= x <= 100
numword_re2 = alternates([fr"{alternates(tens)}([ -]{alternates(ones)})?"]+teens+ones+['zero','one[ -]hundred'])

count_re = fr"\b(?P<count>[5-9]|[1-9][0-9]|[1-9][0-9][0-9]|{numword_re1}) (?P<count_term>(?:critic(?:al)? |professional )?review(?:er)?s|(?:surveyed |professional )?critics|votes)"
average_re = fr"\b(?P<average>([0-9]|10)(\.\d\d?)?|{alternates(ones+['zero','ten'])})(?P<outof>/| out of )(?:10|ten)\b"
score_re = fr"\b(?P<score>[0-9]|[1-9][0-9]|100|{numword_re2})(?:%| percent)"


url_re = r"rottentomatoes.com/(?P<rt_id>m/[-A-Za-z0-9_]+)"

# This will be used to match any reference which includes the RT url pattern.
# This is a generalization of the Cite web, Cite news, and Citation templates.
# Can handle edge cases, such as where a template is not used.
t_other = fr'(?P<citeweb>{url_re})'

# {{Cite Rotten Tomatoes}} template
citert_redirects = ["Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"]
t_citert = fr"(?P<citert>{template_pattern(construct_redirects(citert_redirects))})"

# {{Rotten Tomatoes}} template
rt_redirects = ['Rotten Tomatoes', 'Rotten-tomatoes', 'Rotten tomatoes',
'Rottentomatoes.com', 'Rottentomatoes', 'Rotten']
t_rt = fr"(?P<rt>{template_pattern(construct_redirects(map(re.escape, rt_redirects)))})"

# {{Rotten Tomatoes prose}} template
rtprose_redirects = ['Rotten Tomatoes prose', 'RT prose', 'RT']
t_rtprose = fr"(?P<rtprose>{template_pattern(construct_redirects(rtprose_redirects))})"

# {{As of}} template
asof_redirects = ["As of", "Asof"]
t_asof = fr"(?P<asof>{template_pattern(construct_redirects(asof_redirects))})"

t_alternates = alternates([t_other,t_citert,t_rt])
citation_re = fr'(?P<citation><ref(\s+name\s*=\s*"?(?P<refname>[^>]+?)"?)?\s*>((?!<ref).)*?{t_alternates}((?!<ref).)*</ref\s*>)'

# for list-defined references.
# ldref_re = fr'(?P<ldref><ref +name\s*=\s*"?(?P<ldrefname>[^>]+?)"?\s*/>)'

someref_re = fr'\s*(?:<ref(?:(?!<ref).)+?/(?:ref\s*)?>|{template_pattern(r"[rR]")})'
someref_re2 = fr'\s*(?:<ref(?:(?!<ref).)+?/(?:ref\s*)?>|{template_pattern(r"[rR]", disambiguator=2)})'
# matches zero or more consecutive references (not necessarily for RT), use re.DOTALL
anyrefs_re = fr'(?:{someref_re})*'
anyrefs_re2 = fr'(?:{someref_re2})*'

def section(name):
    """
    Returns regex matching the specified section. Case is ignored in name.
    """
    return r'(?<=\n)={2,} *' + fr'(?i:{name})' + r' *={2,}'
notinbadsection = fr"(?<!{section('(?:references(?: and notes)?|notes(?: and references)?|external links|see also|further reading)')}((?!\n==).)*)"

template_re = r'(?(DEFINE)(?P<template>\{(?:[^}{]|(?&template))*\}))'
notincurly = r'(?!((?!\n\n)[^}{]|(?&template))*\})' # i.e. not in template
notincom = r'(?!((?!<!--|\n\n).)*-->)'
notinref = r'(?!((?!<ref|\n\n).)*</ref)'

cn_redirects = ['Citation needed', 'Facts', 'Citeneeded', 'Citationneeded', 'Cite needed', 'Cite-needed',
'Citation required', 'Uncited', 'Cn', 'Needs citation', 'Reference needed',
'Citation-needed', 'Me-fact', 'CB', 'Sourceme', 'Cb', 'Refneeded', 'Source needed',
'Citation missing', 'FACT', 'Cite missing', 'Citation Needed', 'Proveit', 'CN',
'Source?', 'Fact', 'Refplease', 'Needcite', 'Needsref', 'Ref?', 'Citationeeded',
'Are you sure?', 'Citesource', 'Cite source', 'Ref needed', 'Citation requested',
'Needs citations', 'Fcitation needed', 'Need sources', 'Request citation',
'Citation Requested', 'Request Citation', 'Prove it', 'Ctn', 'Citation need',
'PROV-statement', 'Ciation needed', 'Cit', 'Unsourced-inline', 'Ref-needed',
'Fact?', 'Need Citation', 'CitationNeeded', 'No source given', 'Need-ref',
'Citaiton needed', 'Needcitation', 'Citationrequired', 'Unreferenced inline',
'Cita requerida', 'Needs reference', 'Need citation', 'Citn', 'Citazione necessaria',
'Cn needed', 'Needs-cite']
cn_re = template_pattern(construct_redirects(map(re.escape, cn_redirects)))


infobox_film_redirects = ['Infobox film', 'Infobox movie', 'Infobox Hollywood cartoon',
'Infobox Movie', 'Film infobox', 'Infobox Tamil film', 'Infobox Japanese film',
'Infobox Film', 'Infobox short film', 'Infobox Japanese Film']
infobox_film_re = fr'(?i:{template_pattern(construct_redirects(infobox_film_redirects))})'

# Only use Citation, Cite web, or Cite Rotten Tomatoes
valid_citation_template = ['Citation', 'Cite web', 'Cite Rotten Tomatoes',
'Cite', 'Cite study', 'Cite technical standard',
'Cite Technical standard', 'Citation/lua', 'Cite citation', 'Cite citation/lua',
'Cite asin', 'Citație', 'Obra citada', 'Citar ref', 'Web-reference', 'Web cite',
'Cite website', 'Cite-web', 'Citeweb', 'Web citation', 'Cite url', 'Cite blog',
'Cite Web', 'Weblink', 'Cite webpage', 'Cita web', 'C web', 'Cit web',
'Cite web.', 'Cite website article', 'Cite web/lua', 'Cite w', 'Cite wb',
'Chú thích web', 'Ref web', 'Cite URL', 'یادکرد وب', 'Citace elektronické monografie',
'Web reference', '웹 인용', 'Cite we', 'Citat web', 'Citweb', 'مرجع ويب', 'Web link',
'Navedi splet', 'Citaweb', 'استشهاد ويب', 'Ref-web', 'CITEWEB', 'Cite rotten tomatoes',
'Cite rt', 'Cite RT']

if __name__ == "__main__":
    d = {'hi':'bye'}
    print(rtdata_template(**d, qid='234'))



