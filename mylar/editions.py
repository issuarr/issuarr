#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""Collected editions (TPB, HC, Omnibus and the like) told apart from single issues.

Automatic matching keeps a collected edition out of a series of single issues, where
its volume number would otherwise be read as an issue number. Picking a series or an
issue by hand is never limited by this.
"""

import os
import re

# "Absolute" is left out: it is also a line of single-issue series (Absolute Batman).
_WORDS = re.compile(r'(?<![a-z0-9])(?:tpb|trade paperback|hc|hardcover|gn|graphic novel|omnibus|deluxe edition|'
                    r'compendium|epic collection|complete collection|library edition)(?![a-z0-9])', re.I)

# Words that only say the format, never part of a title, so "Saga HC Book 01" is the series Saga.
_FORMAT_TAIL = re.compile(r'(?:\s+(?:tpb|trade paperback|hc|hardcover|gn|graphic novel))+(?:\s+(?:book|vol(?:ume)?\.?))?\s*$', re.I)

COLLECTED_TYPES = ('TPB', 'HC', 'GN')


def _words(text):
    return {w.lower() for w in _WORDS.findall(re.sub(r'[._]+', ' ', text or ''))}


def collected(filename, series=None):
    """True when the file name says the file is a collected edition. Words that are part of
    the series' own name (a series called "... Omnibus") don't count."""
    name = os.path.splitext(os.path.basename(filename or ''))[0]
    return bool(_words(name) - _words(series))


def strip_format(series_name, watchcomic=None):
    """The series name without a trailing format word such as HC or TPB."""
    if not series_name or (watchcomic and _FORMAT_TAIL.search(watchcomic.strip())):
        return series_name
    stripped = _FORMAT_TAIL.sub('', series_name).strip()
    return stripped or series_name


def series_type(comic_type, corrected=None):
    """The series' type, with Edit series' choice over ComicVine's guess. None when unknown."""
    t = corrected if corrected not in (None, '', 'None') else comic_type
    return None if t in (None, '', 'None') else t


def singles(comic_type, corrected=None):
    """True for a series of single issues: Print or Digital, or no type known."""
    return series_type(comic_type, corrected) in (None, 'Print', 'Digital')


def auto_pick(matches, files_collected):
    """The one search result an import can pick by itself, or None to leave it to the user.
    Collected editions only go to a series ComicVine lists as TPB, HC or GN."""
    if files_collected:
        matches = [m for m in matches if m.get('type') in COLLECTED_TYPES]
    return matches[0] if len(matches) == 1 else None
