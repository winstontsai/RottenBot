# This module takes Candidates and computes replacement text.
################################################################################
import re
import sys
import webbrowser
import string
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from dataclasses import dataclass, field
from datetime import date
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from functools import partial

import pywikibot as pwb
import wikitextparser as wtp

from rapidfuzz.fuzz import partial_ratio

from patterns import *
################################################################################

def rating_and_consensus_prose(rt_data):
    title = rt_data.title
    score, count, average = rt_data.tomatometer_score
    consensus = rt_data.consensus
    s = (f"On [[Rotten Tomatoes]], ''{title}'' holds an approval rating " +
f"of {score}% based on {count} reviews, with an average rating of {average}/10.")
    if consensus or int(count)>=20:
        s = s.replace('approval rating of 100%', '[[List of films with a 100% rating on Rotten Tomatoes|approval rating of 100%]]')
        s = s.replace('approval rating of 0%', '[[List of films with a 0% rating on Rotten Tomatoes|approval rating of 0%]]')
    return s, f'The site\'s critical consensus reads, "{consensus}"'

def citation_replacement(rtmatch):
    refname = rtmatch.ref.name if rtmatch.ref else None
    m = rtmatch.movie
    url, title, year, access_date = m.url, m.title, m.year, m.access_date
    s = "<ref"
    s += f' name="{refname}">' if refname else '>'
    template_dict = {
        'url': url,
        'title': f'{title} ({year})',
        'website': '[[Rotten Tomatoes]]',
        'publisher': '[[Fandango Media|Fandango]]',
        'access-date': access_date
    }
    if rtmatch.ref:
        wikitext = wtp.parse(ref.text)
        if wikitext.templates:
            t = wikitext.templates[0]
            if (x:= t.get_arg('archive-url') or t.get_arg('archiveurl')):
                template_dict['archive-url'] = x
                template_dict['url-status'] = 'live'
                if (x:= t.get_arg('archive-date') or t.get_arg('archivedate')):
                    template_dict['archive-date'] = x
    s += construct_template('Cite web', template_dict)
    s += "</ref>"
    return s

def metacritic_prose():
    s = '[[Metacritic]], which uses a weighted average, assigned the film a score of @@ out of 100 based on reviews from @@ critics, indicating "@@@@@@@@@".'

@dataclass
class Edit:
    replacements: list[tuple[str, str]]
    flags: list[str]

@dataclass
class FullEdit:
    title: str
    edits: list[Edit]


def compute_edits(candidates, get_user_input = True):
    """
    The candidates parameter should be
    an iterable of candidate objects.
    """
    with ProcessPoolExecutor() as x:
        for e in x.map(fulledit_from_candidate, candidates):
            if e:
                yield e

def fulledit_from_candidate(cand):
    pass

def _compute_flags(rtmatch, cand, safe_templates_and_wikilinks):
    span = rtmatch.span
    text = cand.text[span[0]:span[1]]
    flags = set()
    
    # Flags related to the film's title
    if re.search(score_re, cand.title):
        flags.add('score pattern in title')
    if re.search(average_re, cand.title):
        flags.add('average pattern in title')

    # Brackets/quotes matched correctly?
    if not balanced_brackets(text):
        flags.add('mismatched brackets/quotes')

    # Other suspicious activity
    if re.search(r'[mM]etacritic', text):
        flags.add("Metacritic")

    if (k:=pattern_count(fr'<ref|{template_re("[rR]")}', text) - bool(rtmatch.ref)):
        flags.add(f"non-RT references ({k})")

    # hide refs
    text_no_refs = re.sub(someref_re, '', text, flags=re.DOTALL)
    if len(text_no_refs) > 700:
        flags.add('long')

    if (k:=pattern_count(rt_re, text_no_refs)) != 1:
        flags.add(f'Rotten Tomatoes count ({k})')

    # no quotes or refs
    text_no_quotes = re.sub(r'".+?"', lambda m:len(m.group())*'"', text_no_refs, flags=re.DOTALL)
    # audience score?
    if pattern_count(r'\b(audience|user|viewer)', text_no_quotes, re.IGNORECASE):
        flags.add('audience/user/viewer')

    if text_no_quotes[-1] not in '."':
        flags.add("suspicious end")
    if not re.match(r"['{[A-Z0-9]", text[0]):
        flags.add("suspicious start")

    wikitext = wtp.parse(text)

    # for x in reversed(wikitext.get_bolds_and_italics(recursive=False)):
    #     x.string = len(x.string) * "'"

    for x in reversed(wikitext.comments):
        x.string = len(x.string) * 'Ξ'

    if wikitext.external_links:
        flags.add('external link')
    for x in reversed(wikitext.external_links):
        x.url = len(x.url) * 'Ξ'

    for x in reversed(wikitext.wikilinks):
        if f'[[{x.title.strip()}]]' not in safe_templates_and_wikilinks:
            flags.add(f'suspicious wikilink ({x.title.strip()})')
        if x.text:
            x.target = 'Ξ'*len(x.target)

    for x in reversed(wikitext.templates):
        if f'Template:{x.normal_name()}' not in  safe_templates_and_wikilinks:
            flags.add(f'suspicious template ({x.normal_name()})')

    for x in reversed(wikitext.get_tags()):
        if tag.name != 'ref':
            flags.append(f'non-ref tag ({tag.name})')
        x.string = len(x.string) * 'Ξ'

    wikitext = str(wikitext)
    # wikitext = re.sub(r'".+?"', lambda m:len(m.group())*'"', wikitext, flags=re.DOTALL)

    k1 = pattern_count(average_re, wikitext)
    if k1 > 1:
        flags.add(f"multiple averages ({k1})")

    k2 = pattern_count(count_re, wikitext)
    if k2 > 1:
        flags.add(f"multiple counts ({k2})")

    k3 = pattern_count(score_re, wikitext)
    if k3 > 1:
        flags.add(f"multiple scores ({k3})")
    elif k3 == 0:
        flags.add("missing score")

    return sorted(flags)

def _suggested_replacements(rtmatch, cand):
    """Assuming no flags, compute suggested replacement."""
    span = rtmatch.span
    text = cand.text[span[0]:span[1]]
    score, count, average = rtmatch.movie.tomatometer_score

    new_prose = text

    if m := re.match(t_rtprose, new_prose):
            temp_dict = {
                '1': score,
                '2': average,
                '3': count,
            }
            new_prose = new_prose.replace(m[0], construct_template('Rotten Tomatoes prose', temp_dict)) 
    else:
        if not pattern_count(average_re, text) or not pattern_count(count_re, text):
            return _complete_replacement(rtmatch, cand)
        elif (m:=re.search(r'ilms with a (100|0)% rating on Rotten Tom', new_prose)) and m[1] != score:
            return _complete_replacement(rtmatch, cand)
        else:
            def repl(m):
                if m['a']:
                    return f'{average}/10'
                if m['c']:
                    return f'{count} {m['count_term']}'
                if m['s']:
                    return score+'%'
            new_prose = re.sub(fr'(?P<a>{average_re})|(?P<c>{count_re})|(?P<s>{score_re})', repl, new_prose)

        # Update "As of"
        if m:=re.search(t_asof, new_prose): # As of template
            old_temp = m[0]
            temp_dict = parse_template(old_temp)[1]
            day, month, year = date.today().strftime("%d %m %Y").split()
            temp_dict['1'], temp_dict['2'] = year, month
            if '3' in temp_dict:
                temp_dict['3'] = day
            new_prose = new_prose.replace(old_temp, construct_template("As of", temp_dict))
        elif m:=re.search(r"[Aa]s of (?=January|February|March|April|May|June|July|August|September|October|November|December|[1-9])[ ,a-zA-Z0-9]{,14}[0-9]{4}(?![0-9])", new_prose):
            old_asof = m[0]
            day, month, year = date.today().strftime("%d %B %Y").split()
            new_date = month + ' ' + year
            if pattern_count(r'[0-9]', old_asof) > 4: # if includes day
                if old_asof[6].isdecimal(): # day before month
                    new_date = f'{day} {month} {year}'
                else:                       # day after month
                    new_date = f'{month} {day}, {year}'
            new_prose = new_prose.replace(old_asof, old_asof[:6] + new_date)
        elif re.search(r"\b[Aa]s of\b", new_prose):
            return _complete_replacement(rtmatch, cand)

        # Not a weighted average???
        new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]( rating| score)?', 'average rating', new_prose)
        new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
        new_prose = new_prose.replace(' a average',' an average')
        if re.search("[wW]eighted", new_prose):
            return _complete_replacement(rtmatch, cand)

    if safe_to_add_consensus1(rtmatch, cand):
        new_prose += ' ' + consensus_prose

    # add reference stuff
    ref = rtmatch.ref
    if not ref:
        new_prose += citation_replacement(rtmatch)

    replacements = [(text, new_prose)]
    if ref:
        replacements.append((ref.text, citation_replacement(rtmatch)))

    return replacements

def _complete_replacement(rtmatch, cand):
    rating, consensus = rating_and_consensus_prose(rtmatch)
    new_text = rating
    ref = rtmatch.ref
    if safe_to_add_consensus1(rtmatch, cand):
        new_text += ' ' + consensus
    if not ref:
        new_text += citation_replacement(rtmatch)

    span = rtmatch.span
    replacements = [(cand.text[span[0]:span[1]], new_text)]
    if ref:
        replacements.append((ref.text, citation_replacement(rtmatch)))

    return replacements

def safe_to_add_consensus1(rtmatch, cand):
    consensus = rtmatch.movie.consensus
    text = cand.text
    if not consensus:
        return False
    p_start, p_end = paragraph_span(rtmatch.span, text)
    s = text[p_start:p_end]    # the paragraph
    if re.search(r'[cC]onsensus', s):
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False
    # create sequence of lowercase letters for similarity comparison
    s_lower = ''.join(x for x in s         if x.islower())
    c_lower = ''.join(x for x in consensus if x.islower())
    # in some edge cases, there are no lowercase
    if not c_lower:
        return False
    if c_lower in s_lower:
        return False
    return True

# def safe_to_add_consensus2(rtmatch, cand):
#     consensus = rtmatch.movie.consensus
#     text = cand.text
#     if not consensus:
#         return False
#     if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
#         return False
#     p_start, p_end = paragraph_span(rtmatch.span, text)

#     paragraph = text[p_start: p_end]
#     paragraph = re.sub(r'{[^}]*}|\[[^]]*\]|<ref(?:(?!<ref).)+?/(?:ref *)?>|<!--.*?-->', '', paragraph)

#     # if re.search(r'[cC]onsensus', paragraph):
#     #     return False
#     #quotations = ''.join(re.findall('"[^"]+"', paragraph))
#     s_lower = ''.join(x for x in paragraph if x in 'aeiou')
#     c_lower = ''.join(x for x in consensus if x in 'aeiou')

#     # in some edge cases, c_lower will be empty
#     if not c_lower:
#         return False

#     max_errors = int(0.2 * len(c_lower))
#     # print(max_errors)
#     # Use fuzzy matching
#     if m:=re.search(fr'({c_lower}){{i,d,e<={max_errors}}}', s_lower):
#         #print(m.group())
#         return False
#     return True

def safe_to_add_consensus3(rtmatch, cand):
    consensus = rtmatch.movie.consensus
    text = cand.text
    if not consensus:
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False
    p_start, p_end = paragraph_span(rtmatch.span, text)

    paragraph = text[p_start: p_end]
    paragraph = re.sub(r'{.*?}|\[.*?\]|<!--.*?-->', '', paragraph, re.DOTALL)
    paragraph = re.sub(someref_re, '', paragraph)
    return partial_ratio(consensus,paragraph,processor=True,score_cutoff=None)


def balanced_brackets(text):
    rbrackets = {
        "]" : "[",
        "}" : "{",
        ")" : "(",
        ">" : "<",
        '"' : '"'
        }
    lbrackets = rbrackets.values()
    stack= []
    for i in text:
        if i in lbrackets:
            stack.append(i)
        elif i in rbrackets:
            if stack and stack[-1]==rbrackets[i]:
                stack.pop()
            else:
                return False
    return not stack

if __name__ == "__main__":
    print(balanced_brackets('{[()](){}}"'))




