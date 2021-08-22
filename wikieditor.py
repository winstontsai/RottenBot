# This module takes Candidates and computes replacement text.
################################################################################
import sys
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from dataclasses import dataclass
from datetime import date
from concurrent.futures import ProcessPoolExecutor, as_completed

import editor
import regex as re
import wikitextparser as wtp

from pywikibot import Page, Site
from rapidfuzz.fuzz import partial_ratio

from patterns import *
################################################################################
@dataclass
class Edit:
    replacements: list[tuple[str, str]]
    flags: set[str]

@dataclass
class FullEdit:
    title: str
    edits: list[Edit]

def compute_edits(candidates, get_user_input = True):
    """
    The candidates parameter should be
    an iterable of candidate objects.
    """
    with open('safe-templates-and-wikilinks.txt', 'r') as f:
        safe_templates_and_wikilinks = set(line[:-1] for line in f)

    with ProcessPoolExecutor() as x:
        futures = {x.submit(fulledit_from_candidate, c) : c for c in candidates}
        for future in as_completed(futures):
            fe = future.result()
            if not fe:
                continue
            if get_user_input:
                _process_manual_reviews(futures[future], fe, safe_templates_and_wikilinks)


def fulledit_from_candidate(cand):
    editlist = []
    for match in cand.matches:
        flags = _compute_flags(match, cand)
        replacements = _suggested_replacements(match, cand)
        editlist.append(Edit(replacements, flags))
    return FullEdit(cand.title, editlist)


def _process_manual_reviews(cand, fe, safe_templates_and_wikilinks):
    for i, edit in enumerate(fe.edits):
        edit.flags -= safe_templates_and_wikilinks
        if not edit.flags:
            continue

        while True:
            pass

        span = cand.matches[i].span
        pspan = paragraph_span(span, cand.text)
        context = cand.text[pspan[0] : pspan[1]]
    
    with open('safe-templates-and-wikilinks.txt', 'w') as f:
        f.write('\n'.join(sorted(safe_templates_and_wikilinks)) + '\n')

def _ask_for_review(cand, edit, safe_templates_and_wikilinks):
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    oldtext, newtext = edit.replacements[0]
    prompt = f"""{FORE.CYAN}An edit in [[{title}]] has been flagged for review.{STYLE.RESET_ALL}
{FORE.YELLOW}Flags = {sorted(edit.flags)}{STYLE.RESET_ALL}
{FORE.GREEN}Old Wikitext------------------------------------------{STYLE.RESET_ALL}
{text[pspan[0]: i] + STYLE.BRIGHT + oldtext + STYLE.RESET_ALL + text[j: pspan[1]]}
{FORE.GREEN}New Wikitext------------------------------------------{STYLE.RESET_ALL}
{STYLE.BRIGHT + newtext + STYLE.RESET_ALL}
{FORE.GREEN}---------------------------------------------{STYLE.RESET_ALL}
Please select an option (s to skip, q to quit):
1) keep edit
2) open text editor for manual edit
3) open [[{title}]] in the browser
4) add/remove safe templates and wikilinks
"""
    print(prompt)
    while (user_input:=input("Your selection: ")) not in ('1','2'):
        if user_input == '3':
            webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
        elif user_input == '4':
            while (user_input:=input('Template/Wikilink to add/remove (Press Enter to finish): ')):
                remove = False
                if user_input[0] == '-':
                    user_input = user_input[1:]
                    remove = True
                if not re.fullmatch(r'Template:.+|\[\[.+\]\]', user_input):
                    print("Use format Template:X or [[X]] to add. Prepend '-' to remove.")
                    continue
                if remove:
                    safe_templates_and_wikilinks.remove(user_input)
                else:
                    safe_templates_and_wikilinks.add(user_input)
        else:
            print("Not a valid selection.")

    print()
    if user_input == '1':
        edit.flags.clear()
    elif user_input == '2':
        new_edit = review_edit(title, text[pspan[0]:pspan[1]], edit)

    elif user_input == 's':
        print(f"Skipping edit.")
    elif user_input == 'q':
        print("Quitting program.")
        sys.exit()  

def review_edit(title, context, edit):
    """
    Opens text editor for user to review edit.
    """
    if not edit.flags: # only review flagged edits
        return
    initial_text = f"""Reviewing edit for [[{title}]].

Remember not to remove a list-defined Rotten Tomatoes reference
since the reference definition will still be replaced.
Leave NEW WIKITEXT empty to skip this edit.
Leave the entire file empty to quit the program.
-------------------------------------------------------------------------------
Old Wikitext:
{context}
-------------------------------------------------------------------------------
TO BE REPLACED   (put wikitext between the arrows):
🡺🡺🡺{edit.replacements[0][0]}🡸🡸🡸
-------------------------------------------------------------------------------
REPLACEMENT TEXT (put wikitext between the arrows):
🡺🡺🡺{edit.replacements[0][1]}🡸🡸🡸
"""
    x = editor.edit(initial_text).decode()
    if x == '':
        print_logger.info('Quitting program.')
        sys.exit()

    old, new = [m[1] for m in re.finditer(r'🡺🡺🡺(.*)🡸🡸🡸', x, re.S)]

    if new:
        # Clear flags so that edit goes through
        edit.flags.clear()
    else:
        # edit should have flags, so it will be skipped
        print('Skipping edit.')
        
    edit.replacements[0] = (old, new)

def _compute_flags(rtmatch, cand):
    """
    Return list of all flags for a match. Flags indicate that a
    human needs to review the edit. An edit should never be made to
    the live wiki if it its flags attribute is nonempty.
    """
    span = rtmatch.span
    text = cand.text[span[0]:span[1]]
    movie = rtmatch.movie
    flags = set()
    
    # Flags related to the film's title
    if re.search(score_re, cand.title+movie.title):
        flags.add('score pattern in title')
    if re.search(average_re, cand.title+movie.title):
        flags.add('average pattern in title')

    # Brackets/quotes matched correctly?
    if not balanced_brackets(text):
        flags.add('mismatched brackets/quotes')

    # Other suspicious activity
    if re.search(r'[mM]etacritic', text):
        flags.add("Metacritic")

    if (k:=pattern_count(fr'<ref|{template_pattern("[rR]")}', text) - bool(rtmatch.ref)):
        flags.add(f"non-RT references ({k})")

    # hide refs
    text_no_refs = re.sub(someref_re, '', text, flags=re.S)
    if len(text_no_refs) > 700:
        flags.add('long')

    if (k:=pattern_count(rt_re, text_no_refs)) != 1:
        flags.add(f'Rotten Tomatoes count ({k})')

    # no quotes or refs
    text_no_quotes = re.sub(r'".+?"', lambda m:len(m.group())*'"', text_no_refs, flags=re.S)
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
        flags.add(f'[[{x.title.strip()}]]')
        if x.text:
            x.target = 'Ξ'*len(x.target)

    for x in reversed(wikitext.templates):
        flags.add(f'Template:{x.normal_name()}')

    for x in reversed(wikitext.get_tags()):
        if tag.name != 'ref':
            flags.add(f'non-ref tag {tag.name}')
        x.string = len(x.string) * 'Ξ'

    wikitext = str(wikitext)
    # wikitext = re.sub(r'".+?"', lambda m:len(m.group())*'"', wikitext, flags=re.S)

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

    return flags

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

def safe_to_add_consensus2(rtmatch, cand):
    consensus = rtmatch.movie.consensus
    text = cand.text
    if not consensus:
        return False
    if len(cand.matches) > 1 and rtmatch.span[0] < text.index('\n=='):
        return False
    p_start, p_end = paragraph_span(rtmatch.span, text)

    paragraph = text[p_start: p_end]
    paragraph = re.sub(r'{.*?}|\[[^]]*\||<!--.*?-->', '', paragraph, re.S)
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


#################################################################################
# Functions for creating replacement text.
#################################################################################
def _suggested_edit(rtmatch, cand):
    flags = _compute_flags(rtmatch, cand)

    use_complete_replacement = False
    flags = set(x for x in _compute_flags(rtmatch, cand) if not re.match(r'\[\[|Template:', x))


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
            return _complete_replacements(rtmatch, cand)
        elif (m:=re.search(r'ilms with a (100|0)% rating on Rotten Tom', new_prose)) and m[1] != score:
            return _complete_replacements(rtmatch, cand)
        else:
            def repl(m):
                if m['a']:
                    return f'{average}/10'
                if m['c']:
                    return f'{count} {m["count_term"]}'
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
            return _complete_replacements(rtmatch, cand)

        # Not a weighted average???
        new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]( rating| score)?', 'average rating', new_prose)
        new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
        new_prose = new_prose.replace(' a average',' an average')
        if re.search("[wW]eighted", new_prose):
            return _complete_replacements(rtmatch, cand)

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

def _complete_replacements(rtmatch, cand):
    rating, consensus = rating_and_consensus_prose(rtmatch)
    new_text = rating
    ref = rtmatch.ref

    if safe_to_add_consensus1(rtmatch, cand):
        new_text += ' ' + consensus
    if not ref and not re.search(refbegin_re, cand.text, re.S):
        new_text += citation_replacement(rtmatch)
    elif ref.list_defined:
        new_text += f'<ref name="{ref.name}" />'

    span = rtmatch.span
    replacements = [(cand.text[span[0]:span[1]], new_text)]
    if ref:
        replacements.append((ref.text, citation_replacement(rtmatch)))

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
    return s, f'The site\'s critical consensus reads, "{consensus}"'

def citation_replacement(rtmatch):
    refname = rtmatch.ref.name if rtmatch.ref else None
    m = rtmatch.movie
    url, title, year, access_date = m.url, m.title, m.year, m.access_date
    s = "<ref"
    s += f' name="{refname}">' if refname else '>'
    template_dict = {
        'url': url,
        'title': title,
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
    s = 'On [[Metacritic]], the film has a weighted average score of 33 out of 100 based on 22 critics, indicating "generally favorable reviews".'


if __name__ == "__main__":
    pass




