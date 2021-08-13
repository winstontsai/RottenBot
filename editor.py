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

import pywikibot as pwb

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
    if refname:
        s += f' name="{refname}">'
    else:
        s += '>'
    s += f"{{{{Cite web|url={url}|title={title} ({year})|website=[[Rotten Tomatoes]]|publisher=[[Fandango Media|Fandango]]|access-date={access_date}}}}}</ref>"
    #s += f"{{{{Cite Rotten Tomatoes |id={d['id']} |type=movie |title={d['title']} |access-date={d['accessDate']}}}}}</ref>"
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
    for cand in candidates:
        if e := compute_edit(cand):
            yield e

def compute_edit(cand):
    fulledit = FullEdit(cand.title, [])
    text = cand.text
    for rtmatch in cand.matches:
        if rtmatch.movie is None or rtmatch.movie.tomatometer_score is None:
            continue

        span, rt_data, flags = rtmatch.span, rtmatch.movie, set()
        score, count, average = rt_data.tomatometer_score
        rating_prose, consensus_prose = rating_and_consensus_prose(rt_data)

        old_text = text[span[0]:span[1]]
        # delete references
        old_no_refs = re.sub(r'<ref(?:(?!<ref).)+?/(?:ref *)?>',
            '', old_text, flags=re.DOTALL)
        # delete comments
        old_no_refs = re.sub(r'<!--.*?-->', '', old_no_refs, flags=re.DOTALL)
        # use straight quotes
        old_no_refs = old_no_refs.translate(str.maketrans('“”‘’','""\'\''))

        # hide title
        brackets_re = r'\s+\([^()]+?\)$'
        title = re.sub(brackets_re, '', cand.title)
        title_rep = '@' * len(title)
        old_no_refs = re.sub(re.escape(title), title_rep, old_no_refs)

        # Preliminary flags
        # ----------------------------------------------------------------------
        if len(old_text) > 800:
            flags.add('long')

        if re.search(r'[mM]etacritic|[mM]C film', old_no_refs):
            flags.add("Metacritic")

        if re.search(r'[fF]ile:]', old_no_refs):
            flags.add('File')

        if re.search('{{[aA]nchor', old_no_refs):
            flags.add('Anchor')

        if pattern_count('Rotten Tomatoe?s',
                re.sub(r'ilms with a (100|0)% rating on Rotten Tom', '', old_no_refs)) > 1:
            flags.add('multiple Rotten Tomatoes')

        if pattern_count(fr'<ref|{template_re("[rR]")}', old_text) - bool(rtmatch.ref):
            flags.add("non-RT ref")

        # check for some suspicious characters
        if old_text[0] not in string.ascii_uppercase+string.digits + "'{[":
            flags.add("suspicious start")

        def bad_end():
            return (
                (old_no_refs[-1] not in '."' and text[span[1]:span[1]+2]!='\n\n') or
                (re.match(t_rtprose, old_text) and old_no_refs[-1]!='}')
            )
        if bad_end():
            flags.add("suspicious end")

        # audience score?
        if pattern_count(r'\b([aA]udience|[uU]ser|[vV]iewer)',
                re.sub(r'".+?"', '', old_no_refs, flags=re.DOTALL)):
            flags.add('audience/user/viewer')

        # ----------------------------------------------------------------------
        # we will update/build up new_prose step by step
        new_prose = old_no_refs

        # First deal with the template {{Rotten Tomatoes prose}}
        if m := re.match(t_rtprose, new_prose):
            temp_dict = {
                '1': score,
                '2': average,
                '3': count,
            }
            new_prose = new_prose.replace(m[0], construct_template('Rotten Tomatoes prose', temp_dict)) 
        else:
            # handle average rating     
            new_prose, k = re.subn(average_re, f'{average}/10', new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.add("multiple averages")
                
            # handle review reviewCount
            new_prose, k = re.subn(count_re, f"{count} \g<count_term>", new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.add("multiple counts")

            # handle score
            if m:=re.search('ilms with a (100|0)% rating on Rotten Tom', old_no_refs):
                if score not in ['100', '0']:
                    new_prose = rating_prose
            else:
                new_prose, k = re.subn(score_re, score + '%', new_prose)
                if k > 1:
                    flags.add('multiple scores')
                    
            # Update "As of"
            if m:=re.search(t_asof, new_prose): # As of template
                old_temp = m[0]
                day, month, year = date.today().strftime("%d %m %Y").split()
                temp_dict = parse_template(old_temp)[1]
                temp_dict['1'], temp_dict['2'] = year, month
                if '3' in temp_dict:
                    temp_dict['3'] = day
                new_temp = construct_template("As of", temp_dict)
                new_prose = new_prose.replace(old_temp, new_temp)
            elif m:=re.search(r"[Aa]s of (?=January|February|March|April|May|June|July|August|September|October|November|December|[1-9])[ ,a-zA-Z0-9]{,14}[0-9]{4}(?![0-9])", new_prose):
                old_asof = m[0]
                day, month, year = date.today().strftime("%d %B %Y").split()
                new_date = month + ' ' + year
                if pattern_count(r'[0-9]', old_asof) > 4: # if includes day
                    if old_asof[6] in string.digits: # begins with day num
                        new_date = f'{day} {month} {year}'
                    else:
                        new_date = f'{month} {day}, {year}'
                new_asof = old_asof[:6] + new_date
                new_prose = new_prose.replace(old_asof, new_asof)
            elif re.search(r"\b[Aa]s of\b", new_prose):
                new_prose = rating_prose

            # Not a weighted average???
            new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]', 'average rating', new_prose)
            new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
            new_prose = new_prose.replace(' a average',' an average').replace('rating rating','rating')
            if re.search("[wW]eighted", new_prose):
                new_prose = rating_prose

        # fix period/quote ending
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        # add consensus if safe
        def safe_to_add_consensus():
            consensus = rt_data.consensus
            if not consensus:
                return False
            p_start, p_end = paragraph_span(span, text)
            s = text[p_start:span[0]] + new_prose + text[span[1]:p_end]
            s_l = ''.join(x for x in s if x in string.ascii_lowercase)
            consensus = re.sub(re.escape(title), title_rep, consensus)
            c_l = ''.join(x for x in consensus if x in string.ascii_lowercase)

            if re.search('[cC]onsensus', s):
                return False
            if len(cand.matches)>1 and span[0]<text.index('\n=='):
                return False
            if c_l in s_l:
                return False
            return True

        if safe_to_add_consensus():
            new_prose += ' ' + consensus_prose

        # if no change, don't produce an edit
        if new_prose == old_no_refs:
            continue

        # add reference stuff
        ref = rtmatch.ref
        if ref and ref.list_defined:
            new_text = new_prose + f'<ref name="{ref.name}" />'
        else:
            new_text = new_prose + citation_replacement(rtmatch)

        # create replacements list
        replacements = [(text[span[0]:span[1]], new_text)]
        if ref and ref.list_defined:
            replacements.append((ref.text, citation_replacement(rtmatch)))

        fulledit.edits.append( Edit(replacements, sorted(flags)) )

    return fulledit if fulledit.edits else None



if __name__ == "__main__":
    pass




