# This module takes Candidates and computes replacement text.

# Currently the safe_templates_and_wikilinks feature is not being used since
# the bot will not be rewriting prose.
################################################################################
import logging
import sys
import webbrowser

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import editor
import regex as re
import wikitextparser as wtp

from colorama import Fore, Style
from pywikibot import Page, Site, ItemPage
from rapidfuzz.fuzz import partial_ratio

import candidates

from patterns import *
from wdeditor import *

logger = logging.getLogger(__name__)
################################################################################

@dataclass
class Edit:
    replacements: list[tuple[str, str]]
    flags: set[str]
    reviewed: bool = False

@dataclass
class FullEdit:
    title: str
    edits: list[Edit]

def compute_edits(candidates, get_user_input = False):
    """
    candidates is an iterable of candidate objects.
    """
    for cand in candidates:
        fe = fulledit_from_candidate(cand)
        if not fe.edits:
            continue
        if get_user_input:
            _process_manual_reviews(cand, fe)
        yield fe

def fulledit_from_candidate(cand):
    with open('safe-templates-and-wikilinks.txt', 'r') as f:
        safe_templates_and_wikilinks = set(line.rstrip('\n') for line in f)

    title, text, matches = cand.title, cand.text, cand.matches

    cand.qid = None
    # find qid of item connected to cand's article
    # try:
    #     cand.qid = ItemPage.fromPage(Page(Site('en','wikipedia'), title)).getID()
    # except pwb.exceptions.NoPageError:
    #     pass

    # update Wikidata items
    # for movie, qid in set((m.movie, m.qid) for m in matches):
    #     add_RTmovie_data_to_item(movie, make_item(qid))

    # Fix duplicated citations, if any. This is a hacky solution.
    # c = Counter(x.movie.url for x in matches)
    # name_generator = (f'rtdata{i}' for i in range(99) if f'rtdata{i}' not in text)
    # for url in c:
    #     if c[url] < 2:
    #         continue

    #     def preferred_ref(match):
    #         ref = match.ref
    #         val = 6
    #         if ref:
    #             val -= 2
    #             if ref.name:
    #                 val -= 2
    #                 if ref.list_defined:
    #                     val -= 2
    #         # extra subtraction to prefer matches found lower in the article
    #         return val - match.span[0] / len(cand.text)
    #     l = sorted((x for x in matches if x.movie.url == url), key=preferred_ref)
    #     if not l[0].ref:
    #         l[0].ref = candidates.Reference('text', name=next(name_generator))
    #     elif not l[0].ref.name:
    #         l[0].ref.name = next(name_generator)
    #     for match in l[1:]:
    #         if not (match.ref and match.ref.name) or match.ref.name==l[0].ref.name:
    #             match._duplicate_refname = l[0].ref.name

    edits = []
    # Compute an Edit for each match
    for match in matches:
        x = _suggested_edit(cand, match, safe_templates_and_wikilinks)
        edits.append(x)

    return FullEdit(title, edits)


def _process_manual_reviews(cand, fe):
    with open('safe-templates-and-wikilinks.txt', 'r') as f:
        safe_templates_and_wikilinks = set(line.rstrip('\n') for line in f)

    for i, edit in enumerate(fe.edits):
        if not edit.flags:
            continue
        _ask_for_review(cand.title, cand.text,
            cand.matches[i], edit, safe_templates_and_wikilinks)
    
    with open('safe-templates-and-wikilinks.txt', 'w') as f:
        for x in sorted(safe_templates_and_wikilinks):
            print(x, file = f)

def _ask_for_review(title, text, rtmatch, edit, safe_templates_and_wikilinks):
    edit.reviewed = True
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    oldtext, newtext = edit.replacements[0]
    print(f"""{Fore.CYAN+Style.BRIGHT}An edit in [[{title}]] has been flagged for review.{Style.RESET_ALL}
{Fore.YELLOW+Style.BRIGHT}Flags = {sorted(edit.flags)}{Style.RESET_ALL}
{Fore.GREEN+Style.BRIGHT}Old Wikitext------------------------------------------{Style.RESET_ALL}
{text[pspan[0]: i] + Style.BRIGHT + oldtext + Style.RESET_ALL + text[j: pspan[1]]}
{Fore.GREEN+Style.BRIGHT}New Wikitext (Replace bolded above)-------------------{Style.RESET_ALL}
{Style.BRIGHT+newtext+Style.RESET_ALL}
{Fore.GREEN+Style.BRIGHT}------------------------------------------------------{Style.RESET_ALL}""")
    prompt = """Select an option ([k]eep edit, open in [e]ditor, open in [b]rowser,
    [r]ecord template/wikilink, [s]kip, or [q]uit): """
    while (user_input:=input(prompt)) not in ('k','e','s','q'):
        if user_input == 'b':
            webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
        elif user_input == 'r':
            while (user_input:=input('Template/wikilink (Press Enter to finish): ')):
                remove = False
                if user_input[0] == '-':
                    remove = True
                    user_input = user_input[1:]
                if not re.fullmatch(r'(T|WL):.+', user_input):
                    print("Use T:Name for templates and WL:Name for wikilinks. Prepend '-' to remove.")
                    continue
                if remove:
                    try:
                        safe_templates_and_wikilinks.remove(user_input)
                    except KeyError:
                        print(f'{user_input} was already unsafe.')
                else:
                    safe_templates_and_wikilinks.add(user_input)
        else:
            print("Invalid selection.")
    print()

    if user_input == 'k':
        edit.flags.clear()
    elif user_input == 'e':
        review_edit(title, text[pspan[0]:pspan[1]], edit)
    elif user_input == 's':
        print(f"Skipping edit.")
        edit.flags.add('skip')
    elif user_input == 'q':
        print("Quitting program.")
        sys.exit()  

def review_edit(title, context, edit):
    """
    Opens text editor for user to review edit.
    """
    initial_text = f"""Reviewing edit for [[{title}]].

Remember not to remove a list-defined Rotten Tomatoes reference
since the reference definition will still be replaced.
Leave either TO BE REPLACED or REPLACEMENT empty to skip this edit.
-------------------------------------------------------------------------------
Context:
{context}
-------------------------------------------------------------------------------
TO BE REPLACED   (put wikitext between the arrows):
🡺🡺🡺{edit.replacements[0][0]}🡸🡸🡸
-------------------------------------------------------------------------------
REPLACEMENT      (put wikitext between the arrows):
🡺🡺🡺{edit.replacements[0][1]}🡸🡸🡸
"""
    x = editor.edit(contents=initial_text).decode()
    old, new = [m[1] for m in re.finditer(r'🡺🡺🡺(.*?)🡸🡸🡸', x, re.S)]

    if not old or not new:
        # edit will have flags, so it will be skipped
        edit.flags.add('skip')
        print('Skipping edit.')
        return
    # Clear the flags so that edit goes through
    edit.flags.clear()
    edit.replacements[0] = (old, new)


#################################################################################
# Functions for creating replacement text.
#################################################################################
def _compute_flags(rtmatch, cand, safe_templates_and_wikilinks):
    """
    Compute initial set of flags for a match.
    Flags indicate that an edit needs review.
    An edit should never be uploaded if its flags attribute is nonempty.
    """
    span = rtmatch.span
    text = cand.text[span[0]:span[1]]
    movie = rtmatch.movie
    flags = set()

    # Remove comments from text
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    # Fix quote style
    text = text.translate(str.maketrans('“”‘’','""\'\''))

    # Flags related to the film's title
    if re.search(score_re, cand.title+movie.title):
        flags.add('score pattern in title')
    if re.search(average_re, cand.title+movie.title):
        flags.add('average pattern in title')

    # Reference other than Rotten Tomatoes?
    if pattern_count(fr'<ref|{template_pattern("[rR]")}', text) - bool(rtmatch.ref):
        flags.add(f"non-RT reference")

    # Shortened footnotes?
    if re.search(r'{{\s*(?:shortened|sfn|harv)', text, flags=re.I):
        flags.add('sfn or harv')

    wikitext = wtp.parse(text)
    # Tags other than ref and nowiki?
    for tag in wikitext.get_tags():
        if tag.name not in ['ref', 'nowiki']:
            flags.add(f'suspicious tag')

    # delete refs (comments already deleted)
    text_no_refs = re.sub(someref_re, '', text, flags=re.S)

    # Check brackets and quotes
    if x := unbalanced_brackets(text_no_refs):
        flags.add(f'unbalanced {x}')

    # Check for other scores which might interfere: Metacritic, IMDb, PostTrak, CinemaScore
    if re.search(r'Metacritic', text_no_refs, flags=re.I):
        flags.add('Metacritic')
    if re.search(r'IMDb', text_no_refs, flags=re.I):
        flags.add('IMDb')
    if re.search(r'PostTrak', text_no_refs, flags=re.I):
        flags.add('PostTrak')
    if re.search(r'CinemaScore', text_no_refs, flags=re.I):
        flags.add('CinemaScore')

    # Commented out because seems useless, pretty much just false positives.
    # if text_no_refs[-1] not in '."':
    #     flags.add("suspicious end")

    # Very rare, usually false positive I think, but harmless
    if not re.match(r"['{[A-Z0-9]", text[0]):
        flags.add("suspicious start")

    wikitext_no_refs = wtp.parse(text_no_refs)
    if wikitext_no_refs.parser_functions:
        flags.add('parser function')
    if wikitext_no_refs.external_links:
        flags.add('external link')
    for x in wikitext_no_refs.wikilinks:
        if x.text:
            x.target = 'a' * len(x.target)

    uses_rtprose = 1 if re.search(t_rtprose, text_no_refs) else 0
    k = pattern_count(score_re, str(wikitext_no_refs)) + uses_rtprose
    if k == 0:
        flags.add('missing score')
    if k > 1:
        flags.add('multiple scores')

    k = pattern_count(average_re, str(text_no_refs)) + uses_rtprose
    # if k == 0:
    #     flags.add('missing average')
    if k > 1:
        flags.add('multiple averages')

    k = pattern_count(count_re, str(text_no_refs)) + uses_rtprose
    # if k == 0:
    #     flags.add('missing count')
    if k > 1:
        flags.add('multiple counts')

    # hide quotes (comments and refs already deleted)
    text_no_quotes = re.sub(r'".+?"', '', text_no_refs, flags=re.S)
    # audience score?
    if pattern_count(r'\b(audience|user|viewer)', text_no_quotes, re.IGNORECASE):
        flags.add('audience/user/viewer')

    wikitext_no_quotes = wtp.parse(text_no_quotes)

    for x in wikitext_no_quotes.wikilinks:
        z = x.title.strip()
        z = f'WL:{z[:1].upper()+z[1:]}'
        if z not in safe_templates_and_wikilinks:
            flags.add(z)

    for x in wikitext_no_quotes.templates:
        z = f'T:{x.normal_name(capitalize=True)}'
        if z not in safe_templates_and_wikilinks:
            flags.add(z)

    return flags

def _suggested_edit(cand, rtmatch, safe_templates_and_wikilinks):
    flags = _compute_flags(rtmatch, cand, safe_templates_and_wikilinks)
    reduced_flags = set(x for x in flags if not re.match(r'(T|WL):', x))
    reduced_flags -= {'Metacritic', 'IMDb', 'PostTrak', 'CinemaScore'}
    reduced_flags -= {'non-RT reference'}

    span = rtmatch.span
    ref = rtmatch.ref
    movie = rtmatch.movie
    score, count, average = movie.tomatometer_score

    old_text = cand.text[span[0]:span[1]]
    new_prose = old_text
    replacements = []

    ############################################################################
    # First, compute new_citation and add it to new_prose.
    # This way subsequent changes won't affect the replacement of the old citation.
    new_citation = citation_replacement(rtmatch)
    # If inside lead section and no ref, don't add one
    if not ref:
        # Don't add reference to lead section
        if span[0] < cand.text.index('\n=='):
            new_citation = ''
        # Don't add reference if shortened footnotes detected
        # This is a naive check
        elif 'sfn or harv' in flags:
            new_citation = ''
    # if duplicated, defer to later citation
    # elif hasattr(rtmatch, '_duplicate_refname'):
    #     new_citation = f'<ref name="{rtmatch._duplicate_refname}" />'
    else:
        refwikitext = wtp.parse(ref.text)
        if refwikitext.templates:
            t = refwikitext.templates[0]
            # cursory check if citation template
            if t.normal_name(capitalize=True) in valid_citation_template:
                # common parameters
                ####################################################################
                d_access_date = {'1': 'access date'}
                if x := t.get_arg('accessdate') or t.get_arg('access-date'): # check for df
                    value = x.value.strip()
                    if re.match(r'\d{4}-', value): # then iso. Template default is mdy.
                        d_access_date['df'] = 'iso'
                    elif re.match(r'\d{4}', value):
                        d_access_date['df'] = 'ymd'
                    elif re.match(r'\d', value):
                        d_access_date['df'] = 'dmy'
                t.del_arg('accessdate')
                t.set_arg('access-date', rtdata_template(**d_access_date, qid=rtmatch.qid))

                new_title = movie.title
                if x := t.get_arg('title'):
                    value = x.value.strip()
                    if value.startswith("''"):
                        new_title = "''"+new_title+"''"
                    if re.search(r'\d{4}\)$', value):
                        new_title += ' (' + movie.year + ')'
                t.set_arg('title', new_title)
                ####################################################################
                # for Cite Rotten Tomatoes parameters
                if t.normal_name(capitalize=True) in citert_redirects:
                    t.set_arg('id', rtdata_template('rtid', noprefix='y', qid=rtmatch.qid))
                    t.set_arg('type', 'm')
                    t.del_arg('season')
                    t.del_arg('episode')
                    if t.has_arg('url-status'):
                        t.set_arg('url-status', 'live')

                # for general citation templates
                else:
                    temp_dict = dict()
                    temp_dict['url'] = movie.url
                    temp_dict['title'] = t.get_arg('title').value.strip()
                    temp_dict['website'] = '[[Rotten Tomatoes]]'
                    temp_dict['publisher'] = '[[Fandango Media|Fandango]]'
                    temp_dict['access-date'] = t.get_arg('access-date').value.strip()
                    if x := t.get_arg('archiveurl') or t.get_arg('archive-url'):
                        temp_dict['archive-url'] = x.value.strip()
                        temp_dict['archive-date'] = (t.get_arg('archivedate') or t.get_arg('archive-date')).value.strip()
                        temp_dict['url-status'] = 'live'
                    if x := t.get_arg('mode'):
                        temp_dict['mode'] = x.value.strip()
                    if x := t.get_arg('postscript'):
                        temp_dict['postscript'] = x.value.strip()
                    refwikitext = wtp.parse(f'<ref>{construct_template(t.normal_name(), temp_dict)}</ref>')

                # for duplicate ref handling. See fulledit_from_candidate.
                if ref.name:
                    refwikitext.get_tags()[0].set_attr('name', ref.name)

                new_citation = str(refwikitext)

    # add EditAtWikidata button
    new_citation = new_citation.replace('</ref', '{{'+f'RT data|edit|qid={rtmatch.qid}' +'}}</ref')

    # Need to compute critics consensus before adding in new_citation.
    safe1 = safe_to_add_consensus1(rtmatch, cand, new_prose)
    safe2 = safe_to_add_consensus2(rtmatch, cand, new_prose)
    if safe2:
        if not safe1:
            flags.add(f'check critics consensus status {safe1} {safe2}')
        if {'Metacritic','IMDb','PostTrak','CinemaScore','non-RT reference'} & flags:
            new_prose += f' The critical consensus on Rotten Tomatoes reads, "{movie.consensus}"'
        else:
            new_prose += f' The site\'s critical consensus reads, "{movie.consensus}"'

    # Add new_citation to new_prose in the right location
    if ref:
        if ref.list_defined:
            replacements = [(ref.text, new_citation)]
        elif safe2:
            new_prose = new_prose.replace(ref.text, '') + new_citation
        else:
            new_prose = new_prose.replace(ref.text, new_citation)
    else:
        new_prose += new_citation

    ###########################################################################
    # Reference and critical consensus have been handled above. Now we continue.

    # Remove comments
    new_prose = re.sub(r'<!--.*?-->', '', new_prose, flags=re.S)
    # Fix quote style
    new_prose = new_prose.translate(str.maketrans('“”‘’','""\'\''))

    # Replace Template:Rotten Tomatoes prose with {{RT data|prose}}
    if m := re.search(t_rtprose, new_prose):
        new_prose = new_prose.replace(m[0], rtdata_template('prose', qid=rtmatch.qid))

    # Handle cases where linked to [[List of films with a 100% rating on Rotten Tomatoes]]
    on_list = re.search(r'\[\[\s*(?:List of )?films with a (100|0)% rating on Rotten Tomatoes\s*\|([^]]+)\]\]', new_prose, flags=re.I)
    if on_list:
        if on_list[1] != score:
            new_prose = new_prose.replace(on_list[0], on_list[2].strip())
            flags.add('no longer 0% or 100%')
    elif m := re.search(r'\[\[\s*(?:List of )?films with a (100|0)% rating on Rotten Tomatoes', new_prose, flags=re.I):
        if m[1] != score:
            flags.add('no longer 0% or 100%')

    # Replace score, count, and and average
    new_prose = re.sub(score_re + notinref,
        rtdata_template('score', qid=rtmatch.qid), new_prose, flags=re.S)
    if not {'Metacritic'} & flags:
        new_prose = re.sub(count_re + notinref,
            rtdata_template('count', qid=rtmatch.qid)+r' \g<count_term>', new_prose, flags=re.S)
    if not {'IMDb'} & flags:
        new_prose = re.sub(average_re + notinref,
            rtdata_template('average', qid=rtmatch.qid), new_prose, flags=re.S)

    # Fix Wikilink target so that it doesn't use {{RT data}}
    new_prose = re.sub(r'ilms with a \{\{RT data\|score.*?\}\} rating on Rotten', fr'ilms with a {score}% rating on Rotten', new_prose)

    # Update "As of" date
    if m:=re.search(t_asof, new_prose, flags=re.S):
        d = parse_template(m[0])[1]
        if '3' in d:
            d['4'] = 'd'
        if '2' in d:
            d['3'] = 'm'
        if '1' in d:
            d['2'] = 'y'
            if re.search(r'[a-z]', d['1']): # if has letter, assume month is incorrectly put here
                d['3'] = 'm'
        new_prose = new_prose.replace(m[0], rtdata_template('as of', **d, qid=rtmatch.qid))
    elif m:=re.search(r"[Aa]s of (?=Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|[1-9]|early|mid|late).{,14}(?<![0-9])[0-9]{4}(?![0-9])" + notinref, new_prose, flags=re.S):
        d = {'1':'as of', '2':'y', '3':'m'}
        if pattern_count('[0-9]', m[0]) > 4: # if includes day
            d['4'] = 'd'
            if not m[0][6].isdecimal(): # if not day before month
                d['df'] = 'US'
        if m[0][0] == 'a':
            d['lc'] = 'y'
        d['qid'] = rtmatch.qid
        new_prose = new_prose.replace(m[0], rtdata_template(**d))
    elif re.search(r"\b[Aa]s of\b" + notinref, new_prose, flags=re.S):
        flags.add('As of')

    # Not a weighted average??? At the very least unsourced.
    if not {'Metacritic','IMDb'} & flags:
        for wl in wtp.parse(new_prose).wikilinks:
            z = wl.title.strip().lower()
            if re.match(r'weighted (average|(arithmetic )?mean)|average (rating|score)|rating average', z):
                repl = wl.text.strip() if wl.text else wl.title.strip()
                new_prose = new_prose.replace(str(wl), repl)
        new_prose = re.sub(' weighted ' + notinref, ' ', new_prose, flags=re.S)
        new_prose = re.sub(' a average' + notinref, ' an average', new_prose, flags=re.S)

    # remove "rare" adjective since it is subjective
    new_prose = re.sub(r'rare (0%|100%|\[\[List|approval rating)', r'\1', new_prose)

    # An xx% rating vs a xx% rating...
    if score.startswith('8') or score in ('11', '18'):
        new_prose = new_prose.replace(' a {{RT data|score', ' an {{RT data|score')
    else:
        new_prose = new_prose.replace(' an {{RT data|score', ' a {{RT data|score')
    if average.startswith('8'):
        new_prose = new_prose.replace(' a {{RT data|average', ' an {{RT data|average')
    else:
        new_prose = new_prose.replace(' an {{RT data|average', ' a {{RT data|average')

    # Minor (usually correct) fixes
    new_prose = new_prose.replace('"..', '".')
    new_prose = new_prose.replace('.".', '."')
    new_prose = new_prose.replace('".', '."')
    new_prose = re.sub(someref_re, lambda h: h[0].lstrip(), new_prose, flags=re.S)

    # remove citation needed template
    new_prose = re.sub(cn_re, '', new_prose, flags=re.S)

    replacements = [(old_text, new_prose)] + replacements

    # remove qid= parameter if superfluous
    if True or cand.qid == rtmatch.qid:
        replacements = [(z[0], z[1].replace(f'|qid={rtmatch.qid}', '')) for z in replacements]

    return Edit(replacements, reduced_flags)

def citation_replacement(rtmatch):
    ref, movie = rtmatch.ref, rtmatch.movie
    refname = ref.name if ref else None
    if refname:
        s = f'<ref name="{refname}">'
    else:
        s = '<ref>'
    template_dict = {
        # 'url': rtdata_template('url', qid=rtmatch.qid),
        'url': movie.url,
        'title': movie.title,
        'website' : '[[Rotten Tomatoes]]',
        'publisher' : '[[Fandango Media|Fandango]]',
        'access-date': rtdata_template('access date', qid=rtmatch.qid)
    }
    if ref:
        wikitext = wtp.parse(ref.text)
        if wikitext.templates:
            d = parse_template(str(wikitext.templates[0]))[1]
            if (x:= d.get('archive-url') or d.get('archiveurl')):
                template_dict['archive-url'] = x
                template_dict['archive-date'] = d.get('archive-date') or d.get('archivedate') or ''
                template_dict['url-status'] = 'live'
    return s + construct_template('Cite web', template_dict) + "</ref>"

def safe_to_add_consensus1(rtmatch, cand, new_text = ''):
    consensus = rtmatch.movie.consensus
    text = cand.text
    span = rtmatch.span
    if not consensus:
        return False
    p_start, p_end = paragraph_span(rtmatch.span, text)
    s = text[p_start: span[0]] + new_text + text[span[1]: p_end]
    if re.search(r'[cC]onsensus', s):
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False
    s_lower = ''.join(x for x in s         if x.islower())
    c_lower = ''.join(x for x in consensus if x.islower())
    if c_lower in s_lower:
        return False
    return True

# computationally expensive
def safe_to_add_consensus2(rtmatch, cand, new_text = ''):
    consensus, span, text = rtmatch.movie.consensus, rtmatch.span, cand.text
    if not consensus:
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False
    p_start, p_end = paragraph_span(rtmatch.span, text)
    pattern = someref_re + r"|''.*?''|\{.*?\}|\[[^]]*\||<!--.*?-->|\W"
    after     = re.sub(pattern, '', text[span[1]: p_end], flags=re.S)
    new_text  = re.sub(pattern, '', new_text, flags=re.S)
    before    = re.sub(pattern, '', text[p_start:span[0]], flags=re.S)
    consensus = re.sub(pattern, '', consensus, flags=re.S)
    if not consensus: # edge cases such as The Emoji Movie or Tour De Pharmacy
        return False

    def consensus_likely_in_text(t):
        return partial_ratio(consensus,t,score_cutoff=60)
    return not any(map(consensus_likely_in_text, [after, new_text, before]))

def unbalanced_brackets(text):
    rbrackets = {']':'[', '}':'{', ')':'(', '>':'<'}
    lbrackets = rbrackets.values()
    stack= []
    for c in text:
        if c == '"':
            if stack and stack[-1]=='"':
                stack.pop()
            else:
                stack.append('"')
        elif c in lbrackets:
            stack.append(c)
        elif c in rbrackets:
            if stack and stack[-1]==rbrackets[c]:
                stack.pop()
            else:
                return c
    
    return stack[-1] if stack else False

# def _complete_replacements(cand, rtmatch):
#     rating, consensus = rating_and_consensus_prose(rtmatch.movie)
#     new_citation = citation_replacement(rtmatch)
#     span, text, ref = rtmatch.span, cand.text, rtmatch.ref

#     new_text = rating
#     if safe_to_add_consensus2(rtmatch, cand):
#         new_text += ' ' + consensus

#     replacements = []
#     if ref and ref.list_defined:
#         replacements = [(ref.text, new_citation)]
#         new_text += f'<ref name="{ref.name}" />'
#     else:
#         new_text += new_citation
#     replacements = [(text[span[0]:span[1]], new_text)] + replacements
#     return replacements

# def rating_and_consensus_prose(movie):
#     title = movie.title
#     score, count, average = movie.tomatometer_score
#     consensus = movie.consensus
#     s = f"On [[Rotten Tomatoes]], ''{title}'' holds an approval rating of {score}% based on {count} reviews"
#     if average:
#         s += f', with an average rating of {average}/10.'
#     else:
#         s += '.'
#     if consensus or int(count)>=20:
#         s = s.replace('approval rating of 100%', '[[List of films with a 100% rating on Rotten Tomatoes|approval rating of 100%]]')
#         s = s.replace('approval rating of 0%', '[[List of films with a 0% rating on Rotten Tomatoes|approval rating of 0%]]')
#     return (s, f'The site\'s critical consensus reads, "{consensus}"')

if __name__ == "__main__":
    print(rtdata_template('score', qid='Q333'))


