# vim: fileencoding=utf-8
#
# Simple.TV Plex channel plugin
#
# Author: Barry Stump <barry@simple.tv>
################################################################################

# imports
import base64

# global settings
NAME = 'Simple.TV'
VERSION = '1.0.0'
PREFIX = '/video/simpletv'
# TODO: replace hardcoded url base with directory service request
BASE_URL = 'https://stv-p-api1-prod.rsslabs.net'
PAGE_SIZE = 50

# artwork
ART  = 'art-default.jpg'
ICON = 'icon-default.png'
MISSING = 'no-image.png'
GEN1 = 'gen1.jpg'
GEN2 = 'gen2.jpg'


################################################################################
def Start():

    # Set default attributes for various container objects
    ObjectContainer.title1 = NAME
    ObjectContainer.art = R(ART)

    DirectoryObject.thumb = R(MISSING)
    DirectoryObject.art = R(ART)

    EpisodeObject.thumb = R(MISSING)
    EpisodeObject.art = R(ART)

    VideoClipObject.thumb = R(MISSING)
    VideoClipObject.art = R(ART)

    # Set the default cache time to 5 minutes
    HTTP.CacheTime = 300

    # common HTTP headers
    HTTP.Headers['Accept'] = "application/json"
    HTTP.Headers['X-RSSINC-CLIENTTYPE'] = "rokuplayer"
    HTTP.Headers['X-RSSINC-PLAYERVERSION'] = VERSION
    HTTP.Headers['User-Agent'] = 'Simple TV Plex Channel (%s)' % (VERSION)
    if Prefs['username'] and Prefs['password']:
        HTTP.Headers['Authorization'] = 'Basic %s' % \
            (base64.encodestring("%s:%s" % \
                (Prefs['username'], Prefs['password']))[:-1])



################################################################################
def ValidatePrefs():

    user = Prefs['username']
    password = Prefs['password']

    if (not user or not password):
        return ObjectContainer(header=L("Error"), message=L("EmptyCredentials"))

    # make an authentication check request
    url = "%s/auth/users/%s" % (BASE_URL, String.Quote(user))
    try:
        authstring = 'Basic %s' % \
            (base64.encodestring("%s:%s" %(user, password))[:-1])
        req = HTTP.Request(url,
                           headers={'Authorization': authstring},
                           immediate=True,
                           cacheTime=0)
    except Ex.HTTPError as e:
        Log("authentication failed")
        return ObjectContainer(header=L("Error"), message=L("BadAuth"))

    Log("authentication passed")
    HTTP.Headers['Authorization'] = authstring
    return ObjectContainer(header=L("Success"), message=L("PrefsSaved"))


################################################################################
@handler(PREFIX, NAME, art=ART, thumb=ICON)
def MainMenu():

    oc = ObjectContainer(title1=L("MediaServerTitle"), no_cache=True)

    servers = {}

    if Prefs['username'] and Prefs['password']:

        # get the list of media servers (DVRs)
        url = '%s/system/ond/system/mediaservers/1' % (BASE_URL)

        try:
            # cache results for 1 hour
            results = JSON.ObjectFromURL(url, cacheTime=3600)
            for serverJSON in results['MediaServer']:

                # extract necessary data about each media server
                server = {
                    'id':        serverJSON['_id'],
                    'name':      serverJSON['SysConfig']['Name'],
                    'model':     serverJSON['SysInfo']['Model'],
                    'pingurl':   serverJSON['StreamServer']['LocalPingURL'],
                    'localurl':  serverJSON['StreamServer']['LocalStreamBaseURL'],
                    'remoteurl': serverJSON['StreamServer']['RemoteStreamBaseURL'],
                    'islocal':   False,
                }
                thumb=R(MISSING)
                if server['model'] == 'STV_1000':
                    thumb=R(GEN1)
                if server['model'] == 'STV_2000':
                    thumb=R(GEN2)

                # determine whether the device is on the local network or not
                if PingServer(server):
                    server['islocal'] = True

                servers[server['id']] = server

                oc.add(DirectoryObject(
                    key=Callback(GetLibraryRecordings, server_id=server['id']),
                    title=server['name'],
                    tagline="Local" if server['islocal'] else "Remote",
                    thumb=thumb
                ))

        except Ex.HTTPError as e:
            Log("Got HTTPError: "+ repr(e))
            if e.code == 401 or e.code == 403:
                return ObjectContainer(header=L("Error"), message=L("BadAuth"))
            else:
                return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))
        except Exception as e:
            Log("Unknown exception: "+ repr(e))
            return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))

    else:
        oc.header = L("Error")
        oc.message = L("SetAuth")

    # some plex clients need an explicit prefs object to edit preferences
    oc.add(PrefsObject(title=L("PrefsTitle")))


    # remember the list of servers in the global store
    Dict['servers'] = servers

    return oc


####################################################################################################
@route(PREFIX+"/library/{server_id}/groups", page=int)
def GetLibraryRecordings(server_id, page=1):

    # get the server from the global store
    server = Dict['servers'][server_id]

    oc = ObjectContainer(title1=server['name'])

    # sort out the paging variables
    pageStart = (page - 1) * PAGE_SIZE + 1
    pageEnd = page * PAGE_SIZE

    # get the groups in their library
    url = '%s/content/ond/contentmap/%s/groups?composition=mediaserver&state=library&errorstate=success&page=%d-%d' % \
        (BASE_URL, server['id'], pageStart, pageEnd)

    try:
        results = JSON.ObjectFromURL(url)
    except Ex.HTTPError as e:
        Log("Got HTTPError: "+ repr(e))
        if e.code == 401 or e.code == 403:
            return ObjectContainer(header=L("Error"), message=L("BadAuth"))
        else:
            return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))
    except Exception as e:
        Log("Unknown exception: "+ repr(e))
        return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))

    # process each group
    for group in results['Groups']:
        try:
            episodecount = int(group['States'][server['id']]['LibraryCount'])
        except:
            episodecount = None

        oc.add(TVShowObject(
            key=Callback(GetGroupEpisodes, server_id=server['id'], group_id=group['ID'], name=group['Title']),
            rating_key='simpletv/group/'+ group['ID'],
            source_title=NAME,
            title=group['Title'],
            summary=group['Description'],
            episode_count=episodecount,
            thumb=GetPosterImage(group['Images'])
        ))

    # add a next page if necessary
    if results['GroupsCount'] > pageEnd:
        oc.add(NextPageObject(
            key = Callback(GetLibraryRecordings, server_id=server_id, page=page+1),
            title = L("MoreGroups")
        ))


    # no results? bummer
    if len(oc) < 1:
        return ObjectContainer(header=L("EmptyTitle"), message=L("EmptyLibrary"))

    return oc


################################################################################
@route(PREFIX+'/library/{server_id}/group/{group_id}/items', page=int)
def GetGroupEpisodes(server_id, group_id, name="", page=1):

    # get the server from the global store
    server = Dict['servers'][server_id]

    oc = ObjectContainer(title1=name)

    # sort out the paging variables
    pageStart = (page - 1) * PAGE_SIZE + 1
    pageEnd = page * PAGE_SIZE

    url = '%s/content/ond/contentmap/%s/group/%s/iteminstances?composition=mediaserver&state=library&errorstate=success&page=%d-%d' % \
        (BASE_URL, server['id'], group_id, pageStart, pageEnd)

    try:
        results = JSON.ObjectFromURL(url)
    except Ex.HTTPError as e:
        Log("Got HTTPError: "+ repr(e))
        if e.code == 401 or e.code == 403:
            return ObjectContainer(header=L("Error"), message=L("BadAuth"))
        else:
            return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))
    except Exception as e:
        Log("Unknown exception: "+ repr(e))
        return ObjectContainer(header=L("Error"), message=L("NetworkProblem"))

    # process each item (episode)
    for item in results:

        # try to get the actual recorded duration
        try:
            duration = item['Instances'][0]['InstanceState']['RecordedDuration']
        except:
            duration = 0

        # fall back to item duration
        if duration == 0:
            try:
                duration = item['Instances'][0]['Duration']
            except:
                duration = 0

            if duration == 0:
                duration = None

        oc.add(GetEpisode(
            instance_id=item['Instances'][0]['ID'],
            title=item['Title'],
            summary=item['Description'],
            show=name,
            season=item['EpisodeSeasonNo'],
            episode=item['EpisodeSeasonSequence'],
            duration=duration,
            url=GetStreamUrl(server, item['Instances'][0]['InstanceState']['Streams'][0]['Location']),
            thumb=GetPosterImage(item['Images']),
        ))

    # add a next page if necessary (this is occasionally incorrect when there
    # are exactly PAGE_SIZE results in total)
    if len(oc) >= PAGE_SIZE:
        oc.add(NextPageObject(
            key = Callback(GetGroupEpisodes, server_id=server_id, group_id=group_id, name=name, page=page+1),
            title = L("MoreItems")
        ))

    if len(oc) < 1:
        return ObjectContainer(header=name, message=L("EmptyGroup"))

    return oc


################################################################################
def GetEpisode(instance_id, title, summary, show, season, episode, duration, url, thumb, container=False, *args, **kwargs):

    # the double-callback method so that we don't have to have a URL service
    try:
        se = int(season)
        ep = int(episode)
    except:
        se = None
        ep = None

    obj = EpisodeObject(
        key=Callback(GetEpisode,
                     instance_id=instance_id,
                     title=title,
                     summary=summary,
                     show=show,
                     season=season,
                     episode=episode,
                     duration=duration,
                     url=url,
                     thumb=thumb,
                     container=True
        ),
        rating_key='simpletv/instance/'+ instance_id,
        title=title,
        summary=summary,
        show=show,
        duration=(duration*1000) if duration is not None else None,
        thumb=thumb,
        season=se,
        index=ep,
        items=[
            MediaObject(
                parts = [
                    PartObject(
                        key=HTTPLiveStreamURL(url),
                        duration=(duration*1000) if duration is not None else None,
                    ),
                ],
                duration=(duration*1000) if duration is not None else None,
                optimized_for_streaming = True,
            )
        ]
    )

    if container:
        return ObjectContainer(objects=[obj])

    return obj



################################################################################
# utility functions


# get the correct size image from the server list (handles missing images)
def GetPosterImage(images):

    # try to find the 300x300 image
    for image in images:
        if image['Width'] == 300:
            if image['IsGeneric']:
                return R(MISSING)
            else:
                return image['ImageUrl']

    return R(ICON)


# assemble the correct stream url based on whether the server is local or remote
def GetStreamUrl(server, suffix):

    url = server['localurl']
    if not server['islocal']:
        url = server['remoteurl']


    if not url.endswith('/'):
        url = url + '/'

    return url + suffix

# ping the server to determine whether it is local or not
def PingServer(server):

    try:
        resp = HTTP.Request(server['pingurl'], cacheTime=0, timeout=5.0, immediate=True).content
    except:
        resp = ""

    # response is normally "ping" but we'll take any non-empty result just in case
    if len(resp) > 0:
        return True

    return False

