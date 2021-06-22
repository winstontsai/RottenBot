# This module defines some reusable regexes/patterns, and some helper functions.

import re


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
    template = template.strip('{}')
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
    return '{{' + s + '}}'

rt_re = r"[rR]otten [tT]omatoes"

# don't put space in front
score_re = r"(?P<score>([0-9]|[1-9][0-9]|100)(%| percent))"

count_re = r"(?P<count>([5-9]|[1-9][0-9]|[1-9][0-9][0-9]) (?P<count_term>(critical )?reviews|(surveyed )?critics))"
average_re = r"(?P<average>([0-9]|10)(\.\d{1,2})?(/| out of )(10|ten))"

url_re = r"rottentomatoes.com/(?P<rt_id>m/[-a-z0-9_]+)"
url_re2 = r"rottentomatoes.com/(?P<rt_id2>m/[-a-z0-9_]+)"

# Regular expressions for the source/citation, where we will find the
# Rotten Tomatoes URL for the movie.

# for the {{Cite web}} and {{Cite news}} and {{Citation}} templates
citeweb_redirects = [
    "Cite web", "Cite-web", "Citeweb", "Cite Web",
    "Cite news", "Citenews", "Cite-news", "Cite News",
    "Citation", "Cite",
    ]
t_citeweb = fr"(?P<citeweb>{{{{{construct_redirects(citeweb_redirects)}.+?{url_re}.*?}}}})"

# For any reference which includes the rotten tomatoes url pattern.
# Not necessarily a template
# This is a generalization of the Cite web, Cite news, and Citation templates.
# Can handle "abnormal" cases, such as where a template is not used.
# t_other = fr'(?P<citeweb>.+?{url_re}.*?)'
t_other = fr'(?P<citeweb>{url_re})'
t_other2 = fr'(?P<citeweb2>{url_re2})'

# for the {{Cite Rotten Tomatoes}} template
citert_redirects = ["Cite Rotten Tomatoes", "Cite rotten tomatoes", "Cite rt", "Cite RT"]
t_citert = fr"(?P<citert>{{{{{construct_redirects(citert_redirects)}.+?}}}})"
t_citert2 = fr"(?P<citert2>{{{{{construct_redirects(citert_redirects)}.+?}}}})"

# for the {{Rotten Tomatoes}} template
rt_redirects = [ "Rotten Tomatoes", "Rotten-tomatoes", "Rottentomatoes",
                "Rotten tomatoes", "Rotten", "Rottentomatoes.com"]
t_rt = fr"(?P<rt>{{{{{construct_redirects(rt_redirects)}.*?}}}})"
t_rt2 = fr"(?P<rt2>{{{{{construct_redirects(rt_redirects)}.*?}}}})"


# for the {{Rotten Tomatoes prose}} template
rtprose_redirects = [
    'Rotten Tomatoes prose',
    'RT',
    'RT prose', 
]
t_rtprose = fr"(?P<rtprose>{{{{{construct_redirects(rtprose_redirects)}.+?}}}})"


# for inline citations
t_alternates = alternates([t_other,t_citert,t_rt])
t_alternates2 = alternates([t_other2,t_citert2,t_rt2])

#citation_re = fr'(?P<citation><ref( +name *= *(?P<refname>[^<>]+?))? *>.*?{t_alternates}.*?</ref *>)'

#citation_re = fr'(?P<citation><ref( +name *= *(?P<refname>[^<>]+?))? *>[^<>]*?{t_alternates}[^<>]*?</ref *>)'

# using negative lookahead. Don't want glue, i.e. .*?, to contain the substring "<ref"
citation_re = fr'(?P<citation><ref( +name *= *"?(?P<refname>[^>]+?)"?)? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)'
citation_re2 = fr'(?P<citation2><ref( +name *= *"?(?P<refname2>[^>]+?)"?)? *>((?!<ref).)*{t_alternates2}((?!<ref).)*</ref *>)'

# for list-defined references. 
ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>[^>]+?)"? */>)'
ldref_re2 = fr'(?P<ldref2><ref +name *= *"?(?P<ldrefname2>[^>]+?)"? */>)'


rtref_re = alternates([citation_re,ldref_re])
rtref_re2 = alternates([citation_re2,ldref_re2])

# matches zero or more consecutive references (not necessarily for RT)
# needs re.DOTALL
anyrefs_re = r'(<ref( +name *= *[^>]+?)? *>((?!<ref).)*?</ref *>|<ref +name *= *[^>]+? */>)*'



# cand_re1 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + citation_re + fr"(?![^\n]* consensus[^\n<>]*{rtref_re2})(?![^\n.]* consensus)"
# cand_re2 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + citation_re + fr"(?![^\n]* consensus[^\n<>]*{rtref_re2})(?![^\n.]* consensus)"
# cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re + fr"(?![^\n]* consensus[^\n<>]*{rtref_re2})(?![^\n.]* consensus)"
# cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re + fr"(?![^\n]* consensus[^\n<>]*{rtref_re2})(?![^\n.]* consensus)"

cand_re1 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + citation_re + fr"(?![^\n]* consensus)"
cand_re2 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + citation_re + fr"(?![^\n]* consensus)"
cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re + fr"(?![^\n]* consensus)"
cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re + fr"(?![^\n]* consensus)"

cand_re1 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + citation_re + fr"([^\n.]* consensus)?(?![^\n]* consensus)"
cand_re2 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + citation_re + fr"([^\n.]* consensus)?(?![^\n]* consensus)"
cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re + fr"([^\n.]* consensus)?(?![^\n]* consensus)"
cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re + fr"([^\n.]* consensus)?(?![^\n]* consensus)"

cand_re1 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + citation_re + fr'([^\n.]*? consensus[^n]*?".*?")?(?![^\n]* consensus)'
cand_re2 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + citation_re + fr'([^\n.]*? consensus[^n]*?".*?")?(?![^\n]* consensus)'
cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?")?(?![^\n]* consensus)'
cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?")?(?![^\n]* consensus)'

cand_re1 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + citation_re + fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re2 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + citation_re + fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'


cand_re1 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}[^\n]*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re2 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}[^\n]*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re3 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}[^\n]*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re4 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}[^\n]*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'

cand_re1 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re2 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re3 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
cand_re4 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'

cand_re1 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?'
cand_re2 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?'
cand_re3 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?'
cand_re4 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?'

# cand_re1 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?'
# cand_re2 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{citation_re}{anyrefs_re}[.]?'
# cand_re3 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?'
# cand_re4 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{ldref_re}{anyrefs_re}[.]?'



cand_res = [cand_re1, cand_re2, cand_re3, cand_re4]



if __name__ == "__main__":
    print(t_alternates)

