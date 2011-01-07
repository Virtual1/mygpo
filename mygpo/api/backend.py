#
# This file is part of my.gpodder.org.
#
# my.gpodder.org is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# my.gpodder.org is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public
# License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with my.gpodder.org. If not, see <http://www.gnu.org/licenses/>.
#

from mygpo.api.models import Device, Podcast, Subscription, EpisodeToplistEntry
from mygpo.data.mimetype import get_type, CONTENT_TYPES
from mygpo.core import models
from datetime import timedelta

try:
    import json

    # Python 2.5 seems to have a different json module
    if not 'dumps' in dir(json):
        raise ImportError

except ImportError:
    import json


def get_podcasts_for_languages(languages=None, podcast_query=Podcast.objects.all()):
    if not languages:
        return Podcast.objects.all()

    regex = '^(' + '|'.join(languages) + ')'
    return podcast_query.filter(language__regex=regex)


def get_toplist(count, languages=None, types=None):
    """
    Returns count podcasts with the most subscribers (individual users)
    If languages is given as an array of 2-character languages codes, only
    podcasts with the given languages are considered

    For language-specific lists the entries' oldplace attribute is calculated
    based on the same language list
    """

    # if we include all "known" types, ignore this criteria
    # this will then include all types, also unknown ones
    if types and len(types) == len(CONTENT_TYPES):
        types = None

    results = []

    if not languages and not types:
        query = models.Podcast.view('directory/toplist', descending=True,
            limit=count, classes=[models.Podcast, models.PodcastGroup],
            include_docs=True)
        results.extend(list(query))

    elif languages and not types:
        for lang in languages:
            query = models.Podcast.view('directory/toplist_by_language',
                descending=True, limit=count, endkey=[lang],
                startkey=[lang+u'\u9999'],
                classes=[models.Podcast, models.PodcastGroup],
                include_docs=True)
            results.extend(list(query))

    elif types and not languages:
        for type in types:
            query = models.Podcast.view('directory/toplist_by_contenttype',
                descending=True, limit=count, endkey=[type],
                startkey=[type+u'\u9999'],
                classes=[models.Podcast, models.PodcastGroup],
                include_docs=True)
            results.extend(list(query))

    else: #types and languages
        for type in types:
            for lang in languages:
                query = models.Podcast.view('directory/toplist_by_contenttype_language', \
                    descending=True, limit=count, \
                    endkey=[type, lang], startkey=[type, lang+u'\9999'],
                    classes=[models.Podcast, models.PodcastGroup],
                    include_docs=True)
                results.extend(list(query))

    results = list(set(results))
    # sort by subscriber_count and id to ensure same order when subscriber_count is equal
    cur  = sorted(results, key=lambda p: (p.subscriber_count(), p.get_id()),      reverse=True)[:count]
    prev = sorted(results, key=lambda p: (p.prev_subscriber_count(), p.get_id()), reverse=True)[:count]

    return [(p.subscriber_count(), prev.index(p) if p in prev else 0,\
        p.get_old_obj()) for p in cur]


def get_episode_toplist(count, languages=None, types=None):
    """Returns the first num entries of the episode toplist with the given search criteria"""

    # if we include all "known" types, ignore this criteria
    # this will then include all types, also unknown ones
    if types and len(types) == len(CONTENT_TYPES):
        types = None

    entries = EpisodeToplistEntry.objects.all()

    if languages:
        regex = '^(' + '|'.join(languages) + ')'
        entries = entries.filter(episode__podcast__language__regex=regex)

    if types:
        # we can just use a regex here, because searching for the right "type" of an
        # episode is more complex; we first look for all podcasts with the right type
        # and then look through their episodes
        type_regex = '.*(' + '|'.join(types) + ').*'
        entries = entries.filter(episode__podcast__content_types__regex=type_regex)
        entry_list = []
        for e in entries:
            if e.episode.mimetype and get_type(e.episode.mimetype) in types:
                entry_list.append(e)

            if len(entry_list) >= count:
                break

    return entries[:count]


def merge_toplists(podcast_entries, group_entries, sortkey, reverse, count=None):
    """
    merges a podcast- and a group toplist based on the given sortkey
    """
    entries = list(podcast_entries)
    entries.extend(group_entries)
    entries.sort(key=sortkey, reverse=reverse)
    if count:
        entries = entries[:count]
    return entries


def get_random_picks(languages=None, recent_days=timedelta(days=7)):
    all_podcasts    = Podcast.objects.all().exclude(title='').order_by('?')
    lang_podcasts   = get_podcasts_for_languages(languages, all_podcasts)

    if lang_podcasts.count() > 0:
        return lang_podcasts
    else:
        return all_podcasts


def get_all_subscriptions(user):
    return set([s.podcast for s in Subscription.objects.filter(user=user)])


def get_device(user, uid, undelete=True):
    """
    Loads or creates the device indicated by user, uid.

    If the device has been deleted and undelete=True, it is undeleted.
    """
    device, created = Device.objects.get_or_create(user=user, uid=uid)

    if device.deleted and undelete:
        device.deleted = False
        device.save()

    return device


def get_favorites(user):
    favorites = models.EpisodeUserState.view('core/favorite_episodes_by_user', key=user.id)

    episodes = []
    for res in favorites:
        ep = models.Episode.for_id(res['value'])
        if ep:
            episodes.append(ep.get_old_obj())

    return episodes
