# # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## #    
#~ This file is part of NZBmegasearch by 0byte.
#~ 
#~ NZBmegasearch is free software: you can redistribute it and/or modify
#~ it under the terms of the GNU General Public License as published by
#~ the Free Software Foundation, either version 3 of the License, or
#~ (at your option) any later version. 
#~ 
#~ NZBmegasearch is distributed in the hope that it will be useful,
#~ but WITHOUT ANY WARRANTY; without even the implied warranty of
#~ MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#~ GNU General Public License for more details.
#~ 
#~ You should have received a copy of the GNU General Public License
#~ along with NZBmegasearch.  If not, see <http://www.gnu.org/licenses/>.
# # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## # ## #    
from flask import Flask, request, Response, redirect, render_template, send_from_directory, jsonify
import logging
import logging.handlers
import os
import sys
import threading
import SearchModule
import DeepsearchModule
from ApiModule import ApiResponses
from SuggestionModule import SuggestionResponses
from WarperModule import Warper
import megasearch
import config_settings
import miscdefs
import random
import time
import socket
import base64


openssl_imported = True
try:
	from OpenSSL import SSL
except ImportError as exc:
    print ">> Warning: failed to import OPENSSL module ({})".format(exc)
    openssl_imported = False

sessionid_string = base64.urlsafe_b64encode(os.urandom(10)).replace('-','').replace('=','').replace('/','').replace('+','')

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
 	
def reload_all():
	print '>> Bootstrapping...'
	global cfgsets, sugg, ds, mega_parall, wrp, apiresp, auth
	cfgsets = config_settings.CfgSettings()	
	cfgsets.cgen['large_server'] = LARGESERVER
	sugg = SuggestionResponses(cfgsets.cfg, cfgsets.cgen)
	ds = DeepsearchModule.DeepSearch(cfgsets.cfg_deep, cfgsets.cgen)
	mega_parall = megasearch.DoParallelSearch(cfgsets.cfg, cfgsets.cgen, ds)
	wrp = Warper (cfgsets.cgen, cfgsets.cfg, ds)
	apiresp = ApiResponses(cfgsets.cfg, wrp)
	auth = miscdefs.Auth(cfgsets)
	

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
motd = '\n\n~*~ ~*~ NZBMegasearcH ~*~ ~*~'
print motd

DEBUGFLAG = False
LARGESERVER = False

if(len(sys.argv) > 1):
	for argv in sys.argv:
		if(argv == 'help'):
			print ''
			print '`debug`: start in debug mode'
			print '`large`: modality for GUNICORN + NGINX large server'
			print '`daemon`: start in daemon mode, detached from terminal'
			print ''
			exit()

		if(argv == 'debug'):
			print '====== DEBUGMODE DEBUGMODE DEBUGMODE DEBUGMODE ======'
			DEBUGFLAG = True	

		if(argv == 'large'):
			print '====== GUNICORN + NGIX server ======'
			LARGESERVER = True

		if(argv == 'daemon'):
			print '====== DAEMON MODE ======'
			if os.fork():
				sys.exit()

#~ detect if started from gunicorn
oshift_dirconf = os.getenv('OPENSHIFT_DATA_DIR', '')
if( __name__ == 'mega2' and len(oshift_dirconf)==0):
	print '====== GUNICORN + NGIX server ======'
	LARGESERVER = True
	
#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 

cver = miscdefs.ChkVersion(DEBUGFLAG) 
print '>> version: '+ str(cver.ver_notify['curver'])
motd = motd  + ' v.'+str(cver.ver_notify['curver']) + 'large_server: ' + str(LARGESERVER) + ' debug: ' + str(DEBUGFLAG)
cfgsets = config_settings.CfgSettings()
first_time = 0
reload_all()

if (cfgsets.cfg is None or cfgsets.cfg_deep is None ):
	first_time = 1
	'>> It will be configured'	

logsdir = SearchModule.resource_path('logs/')
if(len(os.getenv('OPENSHIFT_DATA_DIR', ''))):
	logsdir = os.environ.get('OPENSHIFT_DATA_DIR')
certdir = SearchModule.resource_path('certificates/')
log = logging.getLogger() 
handler = logging.handlers.RotatingFileHandler(logsdir+'nzbmegasearch.log', maxBytes=cfgsets.cgen['log_size'], backupCount=cfgsets.cgen['log_backupcount']) 
log.setLevel(logging.INFO) 
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)
log.info(motd)
templatedir = SearchModule.resource_path('templates')
app = Flask(__name__, template_folder=templatedir)	 

SearchModule.loadSearchModules()
if(DEBUGFLAG):
	cfgsets.cgen['general_trend'] = 0
	cfgsets.cgen['general_suggestion'] = 0
	print '====== DEBUGFLAG MUST BE SET TO FALSE BEFORE DEPLOYMENT ======'

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
 
@app.route('/poweroff', methods=['GET'])
@auth.requires_auth
def poweroff():
	if(cfgsets.cgen['large_server'] == False):
		if('sid' in request.args):
			if(request.args['sid'] == sessionid_string):
				os._exit(0)
	return main_index()

@app.route('/restart', methods=['GET'])
@auth.requires_auth
def reboot():
	if(cfgsets.cgen['large_server'] == False):
		if('sid' in request.args):
			if(request.args['sid'] == sessionid_string):
				app.restart()
				return render_template('restart.html');
	return main_index();			

@app.route('/legal', methods=['GET'])
@auth.requires_auth
def legal():
	if(cfgsets.cgen['large_server'] == True):
		return render_template('legal.html')
	return main_index()


@app.route('/robots.txt')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])
			
#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 

@app.route('/s', methods=['GET'])
@auth.requires_auth
def search():
	if(first_time and cfgsets.cgen['large_server'] == False):
		return (main_index)
	
	sugg.asktrend_allparallel()	
	#~ parallel suggestion and search
	if(cfgsets.cgen['general_suggestion'] == 1):
		t1 = threading.Thread(target=sugg.ask, args=(request.args,) )
	t2 = threading.Thread(target=mega_parall.dosearch, args=(request.args,)   )
	if(cfgsets.cgen['general_suggestion'] == 1):
		t1.start()
	t2.start()
	if(cfgsets.cgen['general_suggestion'] == 1):	
		t1.join()
	t2.join()

	params_dosearch = {'args': request.args, 
						'sugg': sugg.sugg_info, 
						'trend_movie': sugg.movie_trend, 
						'trend_show': sugg.show_trend, 
						'ver': cver.ver_notify,
						'wrp':wrp,
						'debugflag':DEBUGFLAG,
						'sid': sessionid_string
						}
	return mega_parall.renderit(params_dosearch)

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
@app.route('/config', methods=['GET','POST'])
@auth.requires_conf
def config():
 	if(cfgsets.cgen['large_server'] == False):
		return cfgsets.edit_config()
	else:	
		return main_index();

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
        
@app.route('/warp', methods=['GET'])
def warpme():
	res = wrp.beam(request.args)
	
	if(res == -1):
		return main_index()
	else: 	
		return res
#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 

@app.route('/tosab')
def tosab():
	return jsonify(code=mega_parall.tosab(request.args))

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 
 
@app.route('/', methods=['GET','POST'])
@auth.requires_auth
def main_index():
	#~ flask bug in threads, had to solve like that
	cfgsets.cgen['large_server'] = LARGESERVER
	#~ ~ 
	global first_time
	if(cfgsets.cgen['large_server'] == False):
		if request.method == 'POST':
			cfgsets.write(request.form)
			first_time = 0
			reload_all()

		if first_time == 1:
			return cfgsets.edit_config()

	sugg.asktrend_allparallel()
	cver.chk_update()
	params_dosearch = {'args': '', 
						'sugg': [], 
						'trend': [], 
						'trend_movie': sugg.movie_trend, 
						'trend_show': sugg.show_trend, 
						'ver': cver.ver_notify,
						'debugflag':DEBUGFLAG,
						'sid': sessionid_string}
	return mega_parall.renderit_empty(params_dosearch)

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ 

@app.route('/api', methods=['GET'])
def api():
	if(len(cfgsets.cgen['general_apikey'])):
		if('apikey' in request.args):
			if(request.args['apikey'] == cfgsets.cgen['general_apikey']):
				return apiresp.dosearch(request.args)
			else:	
				return '[API key protection ACTIVE] Wrong key selected'
		else:	
				return '[API key protection ACTIVE] API key required'
	else:
		return apiresp.dosearch(request.args)
			
#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~   

@app.route('/connect', methods=['GET'])
@auth.requires_auth
def connect():
	return miscdefs.connectinfo()
 
#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~   

@app.errorhandler(404)
def generic_error(error):
	return main_index()

#~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~   
 

if __name__ == "__main__":	

	sugg.asktrend_allparallel()
	chost = '0.0.0.0'
	print '>> Running on port '	+ str(cfgsets.cgen['portno'])
	
	ctx = None
	
	if(cfgsets.cgen['general_https'] == 1 and openssl_imported == True):
		print '>> HTTPS security activated' 
		ctx = SSL.Context(SSL.SSLv23_METHOD)
		ctx.use_privatekey_file(certdir+'server.key')
		ctx.use_certificate_file(certdir+'server.crt')
	
	app.run(host=chost,port=cfgsets.cgen['portno'], debug = DEBUGFLAG, ssl_context=ctx)
