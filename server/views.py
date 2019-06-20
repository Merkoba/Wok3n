import os
import re
import json
import shutil
import random
import string
import hashlib
import datetime
import subprocess
import collections
from PIL import Image
from operator import or_
from ipware.ip import get_ip
from mutagen.mp3 import MP3
from django.db.models import Q
from django.db import IntegrityError
from django.db.models import Case, When
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.http import HttpResponseRedirect, HttpResponse
from django.core.context_processors import csrf
from django.shortcuts import render
from django.utils.html import linebreaks, urlize
from server.models import *

from bs4 import BeautifulSoup

root = os.path.dirname(os.path.dirname(__file__))

html_escape_table = {
	"&": "&amp;",
	'"': "\&quot;",
	"'": "&#39;",
	">": "&gt;",
	"<": "&lt;",
	}

html_escape_table2 = {
	"&": "&amp;",
	'"': "&quot;",
	"'": "&#39;",
	">": "&gt;",
	"<": "&lt;",
	}

def html_escape(text):
	return "".join(html_escape_table.get(c,c) for c in text)

def html_escape2(text):
	return "".join(html_escape_table2.get(c,c) for c in text)

def log(s):
	with open(root + '/log', 'a') as log:
		log.write(str(s) + '\n\n')

def random_alpha(n):
	return ''.join(random.choice(string.letters + string.digits) for x in range(n))

def now():
	return datetime.datetime.now()

def create_c(request):
	c = {}
	c.update(csrf(request))
	return c

@csrf_exempt
def main(request):
	if request.method == 'POST':
		if not track_is_ok(request):
			return HttpResponseRedirect('/upload_error')
		track = request.FILES['track']
		track_hash = hashlib.sha1(track.read()).hexdigest()
		try:
			ov = Track.objects.filter(hash=track_hash)[0]
			return HttpResponseRedirect('/' + ov.uid + '/')
		except:
			pass
		track = handle_uploaded_file(request, track, track_hash)
		return HttpResponseRedirect('/' + track.uid + '?key=' + track.key)
	try:
		uid = Track.objects.filter(duration__gte=10).order_by('?')[0].uid
	except:
		uid = '0'
	return HttpResponseRedirect('/' + uid + '/')

def show_track(request, id):
	c = create_c(request)
	time = request.GET.get('time', False)
	play_likes = request.GET.get('play_likes', False)
	if time:
		c['time'] = time
	else:
		c['time'] = 0
	if play_likes:
		c['play_likes'] = 'yes'
	else:
		c['play_likes'] = 'no'
	random_order = request.GET.get('random', False)
	if random_order:
		c['random_order'] = 'yes'
	else:
		c['random_order'] = 'no'
	try:
		track = Track.objects.get(uid=id)
		c['track_id'] = track.uid
		c['extension'] = track.extension
		c['title'] = track.title
		c['days'] = (datetime.datetime.now() - track.date).days
	except:
		c['track_id'] = 0
		c['extension'] = 'nofun'
		c['days'] = -1
		c['title'] = 'nothing to see here'
	return render(request, 'main.html', c)

def get_suggested(track, watched_tracks):
	tracks = Track.objects.filter(duration__gte=10).exclude(uid__in=watched_tracks).order_by('?')[:8]
	entries = []
	for v in tracks:
		entry = {'track_id':v.uid, 'extension':v.extension, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	return suggestions_to_html(entries)

def suggestions_to_html(entries):
	s = "<center><div class='v4'></div>"
	for e in entries:
		s += "<div class='suggestion_entry cursorpointer' onclick='go_to_track(\"" + str(e['track_id']) + "\",\"" + str(e['extension']) + "\",\"" + html_escape(e['title']) + "\")'>"
		s += "<img class='track_thumb' src='/wmedia/thumbs/" + str(e['track_id']) + ".jpg'>"
		s += '<div class="catalog_title" title="' + html_escape2(e['title']) + '">' + html_escape2(e['title'][:15]) + '</div>'
		s += "<div class='catalog_views'>"
		if e['views'] == 1:
			s += "<span>" + str(e['views']) + " play</span>"
		else:
			s += "<span>" + str(e['views']) + " plays</span>"
		if e['comments'] == 1:
			s += "&nbsp;&nbsp;&nbsp; <span>" + str(e['comments']) + " comment</span>"
		else:
			s += "&nbsp;&nbsp;&nbsp; <span>" + str(e['comments']) + " comments</span>"
		s += "</div>"
		s += "</div>"
		s += "</div>"
		s += "<div class='play_next_btn' onclick='play_next($(this),\"" + str(e['track_id']) + "\")'>play next</div>"
	s += "</center>"
	return s

@csrf_exempt
def report_view(request):
	if request.method == 'POST':
		track = Track.objects.get(uid=request.POST['id'])
		track.views += 1
		track.save()
		return HttpResponse('ok')

def track_is_ok(request):
	track = request.FILES['track']
	image = request.FILES['image']
	title = ' '.join(request.POST['title'].strip().split()).replace('\\', '/')[:240]
	if len(title) < 1:
		return False
	if len(track.name.split('.')) < 2:
		return False
	extension = track.name.split('.')[-1].lower()
	extension2 = image.name.split('.')[-1].lower()
	if extension not in ['mp3']:
		return False
	if extension2 not in ['jpg', 'jpeg']:
		return False
	if track._size > 111111111:
		return False
	if image._size > 2222222:
		return False
	try:
		ip = get_ip(request)
		last_track = Track.objects.filter(ip=ip).last()
		if now() - last_track.date < datetime.timedelta(minutes=2):
			return False
	except:
		pass
	return True

def handle_uploaded_file(request, track_file, hash):

	title = ' '.join(request.POST['title'].strip().split()).replace('\\', '/')[:240]

	ip = get_ip(request)
	if not ip:
		ip = 0

	extension = track_file.name.split('.')[-1].lower()
	size = track_file._size / 1000000
	track = Track(title=title, last_modified=now(), ip=ip, date=now(), hash=hash, views=0, extension=extension)

	track.uid = random_alpha(9)
	success = False
	failures = 0

	while not success:
		try:
			track.save()
		except IntegrityError:
			failures += 1
			if failures > 500:
				raise
			else:
				track.uid = random_alpha(9)
		else:
			success = True

	track.key = track.uid + random_alpha(9)

	with open(root + '/wmedia/tracks/' + track.uid + '.' + extension , 'wb+') as destination:
		for chunk in track_file.chunks():
			destination.write(chunk)

	try:
		audio = MP3(root + '/wmedia/tracks/' + track.uid + '.' + track.extension)
		track.duration = int(round(audio.info.length)) 
	except:
		track.duration = 0

	track.size = round(os.path.getsize(root + '/wmedia/tracks/' + track.uid + '.' + track.extension) / (1024*1024.0))

	track.save()

	image_file = request.FILES['image']

	with open(root + '/wmedia/images/' + track.uid + '.jpg', 'wb+') as destination:
		for chunk in image_file.chunks():
			destination.write(chunk)
			
	shutil.copy(root + '/wmedia/img/nothumb.jpg', root + '/wmedia/thumbs/' + track.uid + '.jpg')

	size = (260,145)
	img = Image.open(root + '/wmedia/images/' + track.uid + '.jpg')
	thumb = img.resize(size, Image.ANTIALIAS)
	thumb.save(root + '/wmedia/thumbs/' + track.uid + '.jpg')
	
	return track

def next_track(request):
	watched_tracks = request.GET['watched_tracks']
	idop = request.GET['idop']
	if watched_tracks == '':
		watched_tracks = '0'
	watched_tracks = watched_tracks.split(',')
	if idop != '0':
		try:
			track = Track.objects.get(uid=idop)
			track_id = track.uid
			extension = track.extension
			title = track.title
		except:
			track_id = 0
			title = 'wok3n'
			extension = 'null'
	else:
		try:
			track = Track.objects.filter(duration__gte=10).exclude(uid__in=watched_tracks).order_by('?')[0]
			track_id = track.uid
			extension = track.extension
			title = track.title
		except:
			track_id = 0
			title = 'wok3n'
			extension = 'null'
	data = {'status':'ok', 'track_id':track_id, 'title':title, 'extension':extension}
	return HttpResponse(json.dumps(data), content_type="application/json")

def upload_error(request):
	return render(request, 'upload_error.html')

def add_track(request):
	c = create_c(request)
	return render(request, 'add_track.html', c)

@csrf_exempt
def edit_track(request, id, password):
	t = Track.objects.get(uid=id)
	if request.method == 'POST':
		if request.POST.get('delete', False):
			try:
				os.remove(root + '/wmedia/tracks/' + t.uid + '.' + t.extension)
			except:
				pass
			t.delete()
			return HttpResponseRedirect('/')
		title = ' '.join(request.POST['title'].strip().split()).replace('\\', '/')[:240]
		if len(title) > 0:
			t.title = title
		t.save()
		return HttpResponseRedirect('/' + t.uid)	
	if password == 'pauver' or password == t.key:
		c = create_c(request)
		c['title'] = t.title
		return render(request, 'edit.html', c)

@csrf_exempt
def edit_ads(request, password):
	if request.method == 'POST':
		if request.POST['password'] == 'pauver':
			text = request.POST['text'].strip()
			url = request.POST['url'].strip()
			ad = Ad(text=text, url=url, date=now())
			ad.save()
			c = create_c(request)
			ads = Ad.objects.all().order_by('-date')
			c['ads'] = ads
			c['pw'] = 'pauver'
			return render(request, 'ads_editor.html', c)
		else:
			return HttpResponseRedirect('/')
	if password == 'pauver':
		c = create_c(request)
		ads = Ad.objects.all().order_by('-date')
		c['ads'] = ads
		c['pw'] = 'pauver'
		return render(request, 'ads_editor.html', c)

@csrf_exempt
def edit_one_ad(request, id, password):
	if request.method == 'POST':
		if request.POST['password'] == 'pauver':

			text = request.POST['text'].strip()
			url = request.POST['url'].strip()
			if request.POST.get('udate', False):
				udate = True
			else:
				udate = False

			ad = Ad.objects.get(id=id)
			ad.text = text
			ad.url = url 
			if udate:
				ad.date = now()	
			ad.save()

			return HttpResponseRedirect('/edit_ads/pauver')

		else:
			return HttpResponseRedirect('/')
	if password == 'pauver':
		c = create_c(request)
		ad = Ad.objects.get(id=id)
		c['ad'] = ad
		c['pw'] = 'pauver'
		return render(request, 'edit_one_ad.html', c)

def delete_ad(request, id, password):
	if password == 'pauver':
		ad = Ad.objects.get(id=id)
		ad.delete()
		return HttpResponseRedirect('/edit_ads/pauver')

def ads(request):
	c = create_c(request)
	return render(request, 'ads.html', c)

def likes(request):
	c = create_c(request)
	return render(request, 'likes.html', c)

def watched(request):
	c = create_c(request)
	return render(request, 'watched.html', c)

def uploaded(request):
	c = create_c(request)
	return render(request, 'uploaded.html', c)

def apprvid(request):
	id = request.POST['id']
	track = Track.objects.get(uid=id)
	track.likes += 1
	track.save()
	return HttpResponse('ok')

#
#
#  catalog
#
#

def catalog(request):
	c = create_c(request)
	entries = []
	tracks = Track.objects.filter(duration__gte=10).order_by('-id')[:24]
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	c['entries'] = entries_to_html(entries)
	return render(request, 'catalog.html', c)

def get_latest_entries(request):
	entries = []
	tracks = Track.objects.filter(duration__gte=10).order_by('-id')[:24]
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	entries_html = entries_to_html(entries)
	data = {'status':'ok', 'entries':entries_html}
	return HttpResponse(json.dumps(data), content_type="application/json")

def search_entries(request):
	query = ' '.join(request.GET['query'].strip().split())
	if query == '':
		Track.objects.filter(duration__gte=10).order_by('-id')[:24]
	else:
		tracks = Track.objects.filter(title__icontains=query, duration__gte=10).order_by('-last_modified')[:24]
	entries = []
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	entries_html = entries_to_html(entries)
	data = {'status':'ok', 'entries':entries_html}
	return HttpResponse(json.dumps(data), content_type="application/json")

def sugg_search_entries(request):
	track_id = request.GET['id']
	query = ' '.join(request.GET['query'].strip().split())
	track = Track.objects.get(uid=track_id)
	if query == '':
		suggested = get_suggested(track, [])
	else:
		tracks = Track.objects.filter(title__icontains=query, duration__gte=10).order_by('-last_modified')[:8]
		if len(tracks) > 0:
			entries = []
			for v in tracks:
				entry = {'track_id':v.uid, 'extension':v.extension, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
				entries.append(entry)
			suggested = suggestions_to_html(entries)
		else:
			suggested = "<center><div class='sugg_noresults'>no results</div></center>"
	data = {'status':'ok', 'suggested':suggested}
	return HttpResponse(json.dumps(data), content_type="application/json")

def search_likes(request):
	query = ' '.join(request.GET['query'].strip().split())
	likes = request.GET['likes']
	if likes == '':
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	try:
		ids = likes.split(',')[::-1][:300]
	except:
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	preserved = Case(*[When(uid=pk, then=pos) for pos, pk in enumerate(ids)])
	if query == '':
		tracks = Track.objects.filter(uid__in=ids).order_by(preserved)[:24]
	else:
		tracks = Track.objects.filter(uid__in=ids, title__icontains=query).order_by(preserved)[:24]
	entries = []
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	entries_html = entries_to_html(entries)
	data = {'status':'ok', 'entries':entries_html}
	return HttpResponse(json.dumps(data), content_type="application/json")

def search_watched(request):
	query = ' '.join(request.GET['query'].strip().split())
	watched = request.GET['watched']
	if watched == '':
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	try:
		ids = watched.split(',')[::-1][:300]
	except:
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	preserved = Case(*[When(uid=pk, then=pos) for pos, pk in enumerate(ids)])
	if query == '':
		tracks = Track.objects.filter(uid__in=ids).order_by(preserved)[:24]
	else:
		tracks = Track.objects.filter(uid__in=ids, title__icontains=query).order_by(preserved)[:24]
	entries = []
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	entries_html = entries_to_html(entries)
	data = {'status':'ok', 'entries':entries_html}
	return HttpResponse(json.dumps(data), content_type="application/json")

def search_uploaded(request):
	query = ' '.join(request.GET['query'].strip().split())
	uploaded = request.GET['uploaded']
	if uploaded == '':
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	try:
		ids = uploaded.split(',')[::-1][:300]
	except:
		data = {'status':'ok', 'entries':''}
		return HttpResponse(json.dumps(data), content_type="application/json")
	preserved = Case(*[When(uid=pk, then=pos) for pos, pk in enumerate(ids)])
	if query == '':
		tracks = Track.objects.filter(uid__in=ids).order_by(preserved)[:24]
	else:
		tracks = Track.objects.filter(uid__in=ids, title__icontains=query).order_by(preserved)[:24]
	entries = []
	for v in tracks:
		entry = {'track_id':v.uid, 'title':v.title, 'views':v.views, 'comments':v.comments, 'date':v.date.strftime('%d %b %Y')}
		entries.append(entry)
	entries_html = entries_to_html(entries)
	data = {'status':'ok', 'entries':entries_html}
	return HttpResponse(json.dumps(data), content_type="application/json")

def entries_to_html(entries):
	s = ""
	for e in entries:
		s += "<div class='catalog_entry'>"
		s += "<a href='/" + str(e['track_id']) + "' class='entry'><div class='entry'>"
		s += "<img class='track_thumb' src='/wmedia/thumbs/" + str(e['track_id']) + ".jpg'>"
		s += "<div class='catalog_title' title='" + html_escape2(e['title']) + "'>" + html_escape2(e['title'][:15]) + "</div>"
		s += "</a>"
		s += "<div class='catalog_views'>"
		if e['views'] == 1:
			s += "<span>" + str(e['views']) + " play</span>"
		else:
			s += "<span>" + str(e['views']) + " plays</span>"
		if e['comments'] == 1:
			s += "&nbsp;&nbsp;&nbsp; <span>" + str(e['comments']) + " comment</span>"
		else:
			s += "&nbsp;&nbsp;&nbsp; <span>" + str(e['comments']) + " comments</span>"
		s += "<div class='entry_bottom'><span>" + str(e['date']) + "</span> &nbsp;&nbsp; <span onclick='add_to_playlist(this,\"" + str(e['track_id']) + "\")' class='playlistlink' data-id='" + str(e['track_id']) + "'>add to playlist</span></div>"
		s += "</div>"
		s += "</div>"
		s += "</div>"
	return s

# def enter(request):
# 	auth_logout(request)
# 	if request.method == 'POST':
# 		username = request.POST['username']
# 		password = request.POST['password']
# 		user = authenticate(username=username, password=password)
# 		if user is not None:
# 			auth_login(request, user)
# 			return HttpResponseRedirect('/')
# 		else:
# 			if not register_details_are_ok(username, password):
# 				return HttpResponseRedirect('/enter')
# 			username = username.lower().strip()
# 			email = ''
# 			user = User.objects.create_user(username, email, password)
# 			p = Profile(user=user)
# 			p.save()
# 			user.backend='django.contrib.auth.backends.ModelBackend'
# 			auth_login(request, user)
# 			return HttpResponseRedirect('/')
# 	else:
# 		return render(request, 'enter.html')

# def register_details_are_ok(username, password):
# 	username = username.lower().strip()
# 	if not clean_username(username):
# 		return False
# 	if len(username) < 1 or len(username) > 17:
# 		return False
# 	if len(password) < 1 or len(password) > 30:
# 		return False
# 	return True

# def clean_username(username):
# 	try:
# 		p = re.compile(r"[a-zA-Z0-9]+")
# 		strlist = p.findall(username)
# 		if strlist:
# 			s = ''.join(strlist)
# 			if s == username:
# 				return s
# 			else:
# 				return False
# 		return False
# 	except:
# 		return False

def nignog(request):
	return render(request, 'nignog.html')


#
#
#
#    BOARD
#
#
#

def error(request, code):
	code = int(code)
	c = {}
	if code == 1:
		c['message'] = 'error: debe esperar un minuto para postear otra vez'
	elif code == 2:
		c['message'] = 'error: el texto no debe ser mas largo que 2000 caracteres'
	elif code == 3:
		c['message'] = 'error: no escribio ningun texto'
	elif code == 4:
		c['message'] = 'error: no eligio ninguna imagen'
	return render(request, 'message.html', c)

def save_quotes(post):
	pattern = re.compile('>>(\d+)')
	search = re.findall(pattern, post.text)
	qids = []
	for qid in search:
		if qid not in qids:
			qids.append(qid)
			quote = Post.objects.get(id=qid)
			q = Quote(post=post, quote=quote)
			q.save()

@csrf_exempt
def post_post(request):
	text = request.POST['text'].strip()[:2000]
	track_id = request.POST['track_id']
	track = Track.objects.get(uid=track_id)
	status = check_post(request, track)
	if status == 'ok':
		ip = get_ip(request)
		if not ip:
			ip = 0
		p = Post(track=track, text=text, date=now(), ip=ip)
		p.save()
		track.last_modified = now()
		track.comments += 1
		track.save()
		save_quotes(p)
		data = {'status':'ok'}
	elif status == 'mustwait':
		data = {'status':'error', 'error':'you must wait 30 seconds before commenting again'}
	elif status == 'toolong':
		data = {'status':'error', 'error':'the comment is too long'}
	elif status == 'empty':
		data = {'status':'error', 'error':'the comment is empty'}
	elif status == 'linebreaks':
		data = {'status':'error', 'error':'too many linebreaks'}
	elif status == 'full':
		data = {'status':'error', 'error':'no more comments can be posted'}
	return HttpResponse(json.dumps(data), content_type="application/json")

def check_post(request, track):
	if track.comments >= 300:
		return 'full'
	text = request.POST['text'].strip()[:2000]
	if len(text) == 0:
		return 'empty'
	# if len(text) > 2000:
	# 	return 'toolong'
	if text.count('\n') > 20:
		return 'linebreaks'
	try:
		ip = get_ip(request)
		last_post = Post.objects.filter(ip=ip).last()
		if now() - last_post.date < datetime.timedelta(seconds=30):
			return 'mustwait'
	except:
		pass
	return 'ok'

def get_info(request):
	track_id = request.GET['track_id']
	mode = request.GET['mode']
	track = Track.objects.get(uid=track_id)
	fobs = {}
	fobs['posts'] = []
	posts = Post.objects.filter(track__uid=track_id).order_by('-id')
	for p in posts:
		fobitem = {}
		fobitem['post'] = p
		fobitem['quotes'] = Quote.objects.filter(quote=p)
		fobs['posts'].append(fobitem)
	html_posts = posts_to_html(fobs)
	if mode == 'all':
		date = track.date.strftime('%d %b %Y')
		size = str(track.size)
		extension = track.extension
		watched_tracks = request.GET['watched_tracks']
		watched_tracks = watched_tracks.split(',')
		suggested = get_suggested(track, watched_tracks)
		try:
			ado = Ad.objects.all().order_by('?')[0]
			ad = "<a target='_blank' class='scooter' href='" + ado.url + "'>" + ado.text + "</a>"
		except:
			ad = "<a target='_blank' class='scooter' href='/ads'>your ad can be here</a>"
		data = {'status':'ok', 'posts':html_posts, 'views':track.views, 'date':date, 'size':size, 'extension':extension, 'suggested':suggested, 'ad':ad, 'uid':track.uid}
	else:
		data = {'status':'ok', 'posts':html_posts, 'views':track.views, 'date':'', 'size':'', 'extension':'', 'suggested':'', 'ad':''}
	return HttpResponse(json.dumps(data), content_type="application/json")	

def posts_to_html(fobs):
	s = ""
	for p in fobs['posts']:
		s += "<div class='v1'></div>"
		s += "<div class='reply'>"
		s += "<div class='post_id' id=" + str(p['post'].id) + "> </div>"
		s += "<div class='post_details'>"
		s += "<div onclick='go_to_post(" + str(p['post'].id) + ")' class='post_date'>" + str(p['post'].date) + "</div>"
		s += "<div onclick=\"respond('" + str(p['post'].id) + "')\" class='respond'> reply </div>"
		for q in p['quotes']:
			s += "<div onclick='go_to_post(" + str(q.post.id) + ")' class='header_quote'> >>" + str(q.post.id) + "</div>"
		s += "</div>"
		s += "<div class='post_text'>" + urlize(quotes_text(arrows(linebreaks(html_escape2(p['post'].text))))) + "</div>"
		s += "<div class='clear'></div>"
		s += "</div>"
	return s

def quotes_text(value):
	pat = "&gt;&gt;(\\d+)"
	res = re.sub(pat, check_quotes, value)
	return res

def check_quotes(match):
	g = str(match.group(1))
	return "<div onclick='go_to_post(" + g + ");' class='quote'> >>" + g + "</div>" 	

def arrows(value):
	soup = BeautifulSoup(value, 'html.parser')
	for item in soup.find_all(text=lambda x: x.strip().startswith('>')):
		item.wrap(soup.new_tag("div class='arrow'"))
	return soup.prettify()


### Reports

@csrf_exempt
def report_track_serious(request):

	ip = get_ip(request)
	if not ip:
		ip = 0

	uid = request.POST['track_id']

	track = Track.objects.get(uid=uid)

	try:
		Report.objects.get(ip=ip, track=track, type='serious')
	except:
		report = Report(ip=ip, track=track, type='serious', date=now())
		report.save()
		count = Report.objects.filter(track=track, type='serious').count()
		if count >= 20:
			os.remove(root + '/wmedia/tracks/' + track.uid + '.' + track.extension)
			track.delete()
		
	return HttpResponse('ok')

def show_reports(request, password):
	if password == 'pauver':
		c = create_c(request)
		c['reports'] = Report.objects.all().order_by('-id')[:100]
		return render(request, 'reports.html', c)
	return HttpResponseRedirect('/')

@csrf_exempt
def send_suggestion(request):
	suggestion = request.POST['suggestion'].strip()[:3000]
	the_sugg = Suggestion(text=suggestion, date=now())
	the_sugg.save()

	return HttpResponse('ok')
	
def show_suggestions(request, password):
	if password == 'pauver':
		c = create_c(request)
		c['suggestions'] = Suggestion.objects.all().order_by('-id')[:24]
		return render(request, 'suggestions.html', c)
	else:
		return HttpResponseRedirect('/')