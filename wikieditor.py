# This module takes Candidates and computes replacement text.
################################################################################
import logging
import sys
import webbrowser

from dataclasses import dataclass
from datetime import date

import regex as re
import wikitextparser as wtp

from colorama import Fore, Style
from pywikibot import Page, Site
from rapidfuzz.fuzz import partial_ratio

import editor

from patterns import *

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

def compute_edits(candidates, get_user_input = True):
    """
    candidates is an iterable of candidate objects.
    """
    for cand in candidates:
        fe = fulledit_from_candidate(cand)
        if not fe:
            continue
        if get_user_input:
            _process_manual_reviews(cand, fe)
        yield fe

def fulledit_from_candidate(cand):
    with open('safe-templates-and-wikilinks.txt', 'r') as f:
        safe_templates_and_wikilinks = set(line.rstrip('\n') for line in f)

    editlist = []
    for match in cand.matches:
        if not match.movie or not match.movie.tomatometer_score:
            continue
        editlist.append(_suggested_edit(match, cand, safe_templates_and_wikilinks))
    if editlist:
        return FullEdit(cand.title, editlist)


def _process_manual_reviews(cand, fe):
    with open('safe-templates-and-wikilinks.txt', 'r') as f:
        safe_templates_and_wikilinks = set(line.rstrip('\n') for line in f)

    for i, edit in enumerate(fe.edits):
        if edit.flags <= {'invisible edit'}:
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
    Return set of all flags for a match. Flags indicate that a
    human needs to review the edit. An edit should never be made to
    the live wiki if it its flags attribute is nonempty.
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

    # Check brackets and quotes
    if not balanced_brackets(text):
        flags.add('mismatched brackets/quotes')

    # Metacritic?
    if re.search(r'[mM]etacritic', text):
        flags.add("Metacritic")

    # Reference other than Rotten Tomatoes?
    if pattern_count(fr'<ref|{template_pattern("[rR]")}', text) - bool(rtmatch.ref):
        flags.add(f"non-RT reference")

    wikitext = wtp.parse(text)
    # Tags other than ref and nowiki?
    for tag in wikitext.get_tags():
        if tag.name not in ['ref', 'nowiki']:
            flags.add(f'suspicious tag')
            break

    # delete refs (comments already deleted)
    text_no_refs = re.sub(someref_re, '', text, flags=re.S)

    # Commented out because seems useless, pretty much just false positives.
    # if text_no_refs[-1] not in '."':
    #     flags.add("suspicious end")

    # Very rare, usually false positive I think, but harmless
    if not re.match(r"['{[A-Z0-9]", text[0]):
        flags.add("suspicious start")

    wikitext_no_refs = wtp.parse(text_no_refs)
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
    if k == 0:
        flags.add('missing average')
    if k > 1:
        flags.add('multiple averages')

    k = pattern_count(count_re, str(text_no_refs)) + uses_rtprose
    if k == 0:
        flags.add('missing count')
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

def _suggested_edit(rtmatch, cand, safe_templates_and_wikilinks):
    flags = _compute_flags(rtmatch, cand, safe_templates_and_wikilinks)
    backup = Edit(_complete_replacements(rtmatch, cand), flags)

    reduced_flags = set(x for x in flags if not re.match(r'(T|WL):', x))
    # if reduced_flags:
    #     return backup

    span, ref = rtmatch.span, rtmatch.ref
    text = cand.text[span[0]:span[1]]
    score, count, average = rtmatch.movie.tomatometer_score


    new_prose = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    # Fix quote style
    new_prose = new_prose.translate(str.maketrans('“”‘’','""\'\''))


    if m := re.search(t_rtprose, new_prose):
        # order is score, average, count
        d = parse_template(m[0])[1]
        d['1'] = score
        d['3'] = count
        if float(d['2'])!=float(average):
            z = str(float(average))
            if '.00' in average:
                z = average[0]
            d['2'] = z
        new_prose = new_prose.replace(m[0], construct_template('Rotten Tomatoes prose', d))
    else:
        # if not re.search(average_re, text) or not re.search(count_re, text):
        #     pass
        if (m:=re.search(r'ilms with a (100|0)% rating on Rotten Tom', new_prose)) and m[1] != score:
            flags.add(r'no longer 0% or 100%')
        #else:
        def repl(m):
            #print(m[0])
            if m['average']:
                z = str(float(average))
                if '.00' in average:
                    z = average[0]
                if not re.match(r'\d', m['average']):
                    return z + '/10'
                if float(m['average'])==float(average):
                    return m[0]
                return z + m['outof'] + '10'
            if m['count']:
                return count + ' ' + m['count_term']
            if m['score']:
                return score + '%'
        new_prose = re.sub(fr'{average_re}|{count_re}|{score_re}', repl, new_prose)

        # Update "As of"
        if m:=re.search(t_asof, new_prose): # As of template
            d = parse_template(m[0])[1]
            day, month, year = date.today().strftime("%d %m %Y").split()
            d['1'], d['2'] = year, month
            if '3' in d:
                d['3'] = day
            new_prose = new_prose.replace(m[0], construct_template("As of", d))
        elif m:=re.search(r"[Aa]s of (?=January|February|March|April|May|June|July|August|September|October|November|December|[1-9])[ ,a-zA-Z0-9]{,14}[0-9]{4}(?![0-9])", new_prose):
            day, month, year = date.today().strftime("%d %m %Y").split()
            d = {'1':year, '2':month}
            if pattern_count(r'[0-9]', m[0]) > 4: # if includes day
                d['3'] = day
                if not m[0][6].isdecimal(): # if not day before month
                    d['df'] = 'US'
            if m[0][0] == 'a':
                d['lc'] = 'y'
            new_prose = new_prose.replace(m[0], construct_template("As of", d))
        elif re.search(r"\b[Aa]s of\b", new_prose):
            flags.add('As of')

        # Not a weighted average???
        for wl in wtp.parse(new_prose).wikilinks:
            z = wl.title.strip().lower()
            if re.match(r'weighted (average|(arithmetic )?mean)|average (rating|score)|rating average', z):
                repl = wl.text.strip() if wl.text else wl.title.strip()
                new_prose = re.sub(re.escape(str(wl)), repl, new_prose)
        new_prose = new_prose.replace(' weighted ', ' ')
        new_prose = new_prose.replace(' a average',' an average')

    # Minor (usually correct) fixes
    new_prose = new_prose.replace('"..', '".')
    new_prose = new_prose.replace('.".', '."')
    new_prose = new_prose.replace('".', '."')
    new_prose = re.sub(someref_re, lambda m: m.group().lstrip(), new_prose, flags=re.S)

    if (x:=safe_to_add_consensus1(rtmatch, cand, new_prose)) != (y:=safe_to_add_consensus2(rtmatch, cand, new_prose)):
        flags.add('check critics consensus')
        # print(x, y, '\n', cand.title, '\n')
    if y:
        new_prose += ' ' + rating_and_consensus_prose(rtmatch.movie)[1]

    # Don't make an edit if the prose (without refs) is the same.
    if ref and new_prose == text:
        flags.add('invisible edit')

    replacements = []
    # citation update
    if ref:
        refwikitext = wtp.parse(ref.text)
        if refwikitext.templates:
            t = refwikitext.templates[0]
            if re.search('cit(e|ation)', t.normal_name().lower()):
                if t.get_arg('accessdate'):
                    t.set_arg('accessdate', rtmatch.movie.access_date)
                else:
                    t.set_arg('access-date', rtmatch.movie.access_date)
                new_citation = str(refwikitext)
            else:
                new_citation = citation_replacement(rtmatch)
        else:
            new_citation = citation_replacement(rtmatch)

        if ref.list_defined:
            replacements = [(ref.text, new_citation)]
        else:
            new_prose = re.sub(someref_re, '', new_prose, flags=re.S)
            new_prose += new_citation
    else:
        new_prose += citation_replacement(rtmatch)

    # remove citation needed template
    new_prose = re.sub(cn_re, '', new_prose, flags=re.S)

    replacements = [(text, new_prose)] + replacements

    return Edit(replacements, flags)

def _complete_replacements(rtmatch, cand):
    rating, consensus = rating_and_consensus_prose(rtmatch.movie)
    new_citation = citation_replacement(rtmatch)
    span, text, ref = rtmatch.span, cand.text, rtmatch.ref
    pstart, pend = paragraph_span(span, text)
    text_to_check = text[pstart:span[0]] + text[span[1]:pend]

    new_text = rating
    if safe_to_add_consensus1(rtmatch, cand):
        new_text += ' ' + consensus

    if ref and ref.list_defined:
        new_text += f'<ref name="{ref.name}" />'
    else:
        new_text += new_citation

    span = rtmatch.span
    replacements = [(cand.text[span[0]:span[1]], new_text)]
    if ref and ref.list_defined:
        replacements.append( (ref.text, new_citation) )

    return replacements

def rating_and_consensus_prose(movie):
    title = movie.title
    score, count, average = movie.tomatometer_score
    consensus = movie.consensus
    s = (f"On [[Rotten Tomatoes]], ''{title}'' holds an approval rating " +
f"of {score}% based on {count} reviews, with an average rating of {average}/10.")
    if consensus or int(count)>=20:
        s = s.replace('approval rating of 100%', '[[List of films with a 100% rating on Rotten Tomatoes|approval rating of 100%]]')
        s = s.replace('approval rating of 0%', '[[List of films with a 0% rating on Rotten Tomatoes|approval rating of 0%]]')
    return (s, f'The site\'s critical consensus reads, "{consensus}"')

def citation_replacement(rtmatch):
    ref = rtmatch.ref
    refname = ref.name if ref else None
    m = rtmatch.movie
    s = "<ref" + f' name="{refname}">' if refname else '>'
    template_dict = {
        'url': m.url,
        'title': m.title,
        'website' : '[[Rotten Tomatoes]]',
        'publisher' : '[[Fandango Media|Fandango]]',
        'access-date': m.access_date
    }
    if ref:
        wikitext = wtp.parse(ref.text)
        if wikitext.templates:
            d = parse_template(str(wikitext.templates[0]))[1]
            if (x:= d.get('archive-url') or d.get('archiveurl')):
                template_dict['archive-url'] = x
                if (x:= d.get('archive-date') or d.get('archivedate')):
                    template_dict['archive-date'] = x
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

def safe_to_add_consensus2(rtmatch, cand, new_text = ''):
    consensus, span, text = rtmatch.movie.consensus, rtmatch.span, cand.text
    def consensus_likely_in_text(t):
        return partial_ratio(consensus,t,score_cutoff=60)

    if consensus is None:
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False

    p_start, p_end = paragraph_span(rtmatch.span, text)
    pattern = someref_re + r"|''.*?''|\{.*?\}|\[[^]]*\||<!--.*?-->|\W"

    before   = re.sub(pattern, '', text[p_start:span[0]], flags=re.S)
    after    =  re.sub(pattern, '', text[span[1]: p_end], flags=re.S)
    new_text = re.sub(pattern, '', new_text, flags=re.S)

    consensus = re.sub(pattern, '', consensus, flags=re.S)
    if not consensus: # edge cases such as The Emoji Movie or Tour De Pharmacy
        return False

    return not any(map(consensus_likely_in_text, [after, new_text, before]))

def balanced_brackets(text):
    rbrackets = {']':'[', '}':'{', ')':'(', '>':'<'}
    lbrackets = rbrackets.values()
    stack= []
    for i in text:
        if i == '"':
            if stack and stack[-1]=='"':
                stack.pop()
            else:
                stack.append('"')
        elif i in lbrackets:
            stack.append(i)
        elif i in rbrackets:
            if stack and stack[-1]==rbrackets[i]:
                stack.pop()
            else:
                return False
    return not stack




if __name__ == "__main__":
    pass




