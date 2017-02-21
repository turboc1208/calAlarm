#
# Alarm Clock - for HomeAssistant
#
# Written By : Chip Cox
#
# Jan 8, 2017 - Added Comments
#####
# requires tzlocal                           sudo pip3 install tzlocal
# requires httplib2                          sudo pip3 install httplib2  (major pain in the back to get it installed right)
# requires googleapiclient                   sudo pip3 install --upgrade google-api-python-client 
######

import appdaemon.appapi as appapi
import inspect
import httplib2
import sys
import json
from datetime import datetime
from tzlocal import get_localzone
import binascii
import os
from googleapiclient.discovery import build
from oauth2client import tools
from oauth2client.file import Storage
from oauth2client.client import AccessTokenRefreshError
from oauth2client.client import OAuth2WebServerFlow
         
class calalarm(appapi.AppDaemon):
  
  # Created an initialization file just to mimic AD it's called from __init__
  def initialize(self):
    self.alarmstate={}                                                             # is the alarm active or inactive for each room
    self.alarms={}                                                                 # holds the actual alarms
    filedir=self.args["configfiledir"]                                             # directory for config file
    self.client_id=self.args["client_id"]                                          # google client id and secret
    self.client_secret=self.args["client_secret"]
    self.filename=filedir + "/" + "haalarmstate.dat"                               # config filename

    self.http = httplib2.Http()                                                    # setup infrastructure for talking to google.
    storage = Storage(filedir+'/calalarm/credentials.dat')
    self.tzoffset="-06:00"


    # OAUTH Authentication (Pain in the backside)
    self.scope = 'https://www.googleapis.com/auth/calendar'                        # The scope URL for read/write access to a user's calendar data
    # Create a flow object. This object holds the client_id, client_secret, and
    # scope. It assists with OAuth 2.0 steps to get user authorization and
    # credentials.
    self.flow = OAuth2WebServerFlow(self.client_id, self.client_secret, self.scope)
    credentials = storage.get()

    # need to add this so we can create new credentials if needed
    sys.argv.append("noauth_local_webserver=True")

    # handle things if no credentials or invalid credentials are found
    if credentials is None or credentials.invalid:
      credentials = tools.run_flow(self.flow, self.storage, tools.argparser.parse_args())

    # Create an httplib2.Http object to handle our HTTP requests, and authorize it
    # using the credentials.authorize() function.
    self.http = credentials.authorize(self.http)
    self.service = build('calendar', 'v3', http=self.http)

    ######  Next generate this from group in HA
    self.rooms={}
    self.rooms=eval(self.args["rooms"])
    self.log("rooms={}".format(self.rooms))
    #self.rooms=["master","sam","charlie"]
    for room in self.rooms:
      self.alarms[room]={"handle":""}
    self.readalarmstate()
    ####### Build list of rooms based on calendars assigned to room groups in HA
    #self.roomowners={"chip":{"room":"master","calendar":""},
    #                   "susan":{"room":"master","calendar":""},
    #                   "sam":{"room":"sam","calendar":""},
    #                   "charlie":{"room":"charlie","calendar":""}}
    self.roomowners=eval(self.args["roomowners"])
    self.log("roomowners={}".format(self.roomowners))
    entity="calendar"
    c=self.loadCalendars()
    #self.log("c={}".format(c))

    for cal in c:
      #self.log("cal={}".format(c[cal]))
      if c[cal] in self.roomowners:
         self.roomowners[c[cal]]["calendar"]=cal

    self.readalarmstate()
      # setup listeners
    boolean_list=self.build_entity_list("group.alarm_clocks",['input_boolean'])
    self.log("boolean_list={}".format(boolean_list))
    for switch in boolean_list:
      teststate=self.listen_state(self.input_boolean_changed, switch)
    teststate=self.listen_event(self.restartHA,"ha_started")
    teststate=self.listen_state(self.calchanged,"calendar")
    teststate=self.run_every(self.checkifcalchanged,self.datetime(),15*60)

      # setup initial values in HA based on saved alarm settings
    for room in self.rooms:
      self.schedulealarm(room)
    
  def authenticateCalendars(self):
    # Create a flow object. This object holds the client_id, client_secret, and
    # scope. It assists with OAuth 2.0 steps to get user authorization and
    # credentials.
    self.flow = OAuth2WebServerFlow(self.client_id, self.client_secret, self.scope)
    credentials = self.storage.get()
    #self.log("before argv={}".format(sys.argv))
    sys.argv.append("auth_host_name='localhost'")
    sys.argv.append("auth_host_port=[8080,8090]")
    sys.argv.append("logging_level='ERROR'")
    sys.argv.append("noauth_local_webserver=False")
    #self.log("After argv={}".format(sys.argv))
    # handle things if no credentials or invalid credentials are found
    if credentials is None or credentials.invalid:
      credentials = tools.run_flow(self.flow, self.storage, tools.argparser.parse_args())

    # Create an httplib2.Http object to handle our HTTP requests, and authorize it
    # using the credentials.authorize() function.
    self.http = credentials.authorize(http)

  #########################
  # returns list of calendars to look at
  # in my case it returns my calendar along with my wife and kids calendars    
  #########################
  def loadCalendars(self):
    #self.service = build('calendar', 'v3', http=self.http)
    page_token=None              # initialize page_token
    c={}
    try:
      while True:
        cal_list = self.service.calendarList().list(pageToken=page_token).execute()
        for cal in cal_list["items"]:
          if not cal["id"].find("@group")>=0:   #group calendars are like holidays and contacts don't do those
            c[cal["id"]]=cal["id"][0:cal["id"].find(".")]
        return c if not c==None else {}
    except AccessTokenRefreshError:  # handle credentials expiring while we are running
      # The AccessTokenRefreshError exception is raised if the credentials
      # have been revoked by the user or they have expired.
      self.log ("The credentials have been revoked or expired, please re-run"
             "the application to re-authorize")
 

  # handle HA restart
  def restartHA(self,event_name,data,kwargs):
    #self.log("HA event {}".format(event_name),level="WARNING")
    # read calendar and update HA alarm time based on results.
    self.log("HA Restarted need to check current state")
    self.readalarmstate()
    for room in self.rooms:
      if not self.alarms[room]["handle"]=="":
        self.cancel_timer(self.alarms[room]["handle"])
      ############## Change this to set HA state based on data read from file
      self.set_state("input_boolean."+room+"alarm",state=self.alarmstate[room]["active"])


    # add alarm to dictionary
  def addalarm(self,room,alarmtime):
    # schedule the alarm and add handle to the dictionary so it can be cancled if needed
    # Dictionary should be {"room":{"handle":alarmhandle},"room2":{"handle":alarmhandle}}
    self.log("Adding alarm")
    self.log("room= {} handle={}".format(room,self.alarms[room]["handle"]))
    #self.log("alarmtime={}".format(alarmtime))
    if datetime.strptime(alarmtime,self.caldateFormat(alarmtime))>datetime.now():
      if not self.alarms[room]["handle"]=="":
        timer_info=self.info_timer(self.alarms[room]["handle"])
        if not timer_info==None:
          info_time=timer_info["info_time"]
          info_interval=timer_info["info_interval"]
          info_kwargs=timer_info["info_kwargs"]

          self.log("existing timer {}, interval {}, kwargs={}".format(info_time,info_interval,info_kwargs))
          if info_time>datetime.strptime(alarmtime,self.caldateFormat(alarmtime)):
            self.log("replace alarm")
            self.cancel_timer(self.alarms[room]["handle"])
            self.alarms[room]["handle"]=self.run_at(self.alarm_lights,datetime.strptime(alarmtime,self.caldateFormat(alarmtime)),arg1=room)
            self.log("Alarm updated for {} room to alarmtime={}".format(room,alarmtime))
          else:
            self.log("Duplicate alarm do nothing")
        else:
          self.log("invalid timer, removing")
          self.alarms[room]["handle"]=""
      else:
        self.alarms[room]["handle"]=self.run_at(self.alarm_lights,datetime.strptime(alarmtime,self.caldateFormat(alarmtime)),arg1=room)
        self.log("new alarm added for {} room at alarmtime={}".format(room,alarmtime))
    else:
      self.log("Alarm time {} already past".format(alarmtime))

  def checkifcalchanged(self,kwargs):
    for owner in self.roomowners:
      self.schedulealarm(self.roomowners[owner]["room"])
    self.print_calendar()

  def calchanged(self,entity,attribute,old,new,kwargs):
    if not old==new:
      for cal in self.roomowners:
        if self.roomowners[cal]["calendar"]==entity:
          self.schedulealarm(self.roomowners[cal]["room"])
            
  # input boolean for turning the alarm on or off
  def input_boolean_changed(self, entity, attribute, old, new, kwargs):
    self.log("in handle_input_boolean")
    # Get room from entity name
    room=entity[entity.find(".")+1:entity.find("alarm")]
    if new=="on":
      if room in self.rooms:
        if not room in self.alarmstate:
          self.alarmstate[room]={}
        self.alarmstate[room]["active"]=new
        self.log("room {} active set to {}".format(room,new))
        self.schedulealarm(room)
    else:
      if room in self.rooms:
        if not room in self.alarmstate:
          self.alarmstate[room]={}
        self.alarmstate[room]["active"]=new                    # alarm has been deactivated
        if not self.alarms[room]["handle"]=="":            #cleanup any current alarms
          self.cancel_timer(self.alarms[room]["handle"])
          self.alarms[room]["handle"]=""
    self.savealarmstate()

  def readalarmstate(self):
    if os.path.exists(self.filename):
      fin=open(self.filename,"rt")
      self.alarmstate=json.load(fin)
      fin.close()
    else:
      self.alarmstate={}
      for room in self.rooms:
        self.alarmstate[room]={}
        self.alarmstate[room]["active"]=self.get_state("input_boolean."+room+"alarm")
      self.savealarmstate()

  def savealarmstate(self):
    fout=open(self.filename,"wt")
    json.dump(self.alarmstate,fout)
    fout.close()
    self.setfilemode(self.filename,"rw-rw-rw-")

  def setfilemode(self,infile,mode):
    if len(mode)<9:
      self.log("mode must bein the format of 'rwxrwxrwx'")
    else:
      result=0
      for val in mode: 
        if val in ("r","w","x"):
          result=(result << 1) | 1
        else:
          result=result << 1
      self.log("Setting file to mode {} binary {}".format(mode,bin(result)))
      os.chmod(infile,result)

  def getRoomOwner(self,room):
    ownerlist=[]
    for owner in self.roomowners:
      if self.roomowners[owner]["room"]==room:
        ownerlist.append(owner)
    return ownerlist

  def schedulealarm(self,room):
    owner=self.getRoomOwner(room)
    for o in owner:
      meeting=self.getMeetings(self.roomowners[o]["calendar"])
      for m in meeting:
        if meeting[m].upper()=="WAKEUP":
          self.addalarm(room,m)
    
  def getMeetings(self,cal):    # pass in Calendar (not users name)
    now = datetime.now()
    strtime = now.isoformat('T')+self.tzoffset
    meetings={}
    # now go and get the events from our current cal and starting now none from the past.
    request = self.service.events().list(calendarId=cal,timeMin=strtime)
    # Loop until all pages have been processed.
    while request != None:
      # Get the next page.
      response = request.execute()
      # Accessing the response like a dict object with an 'items' key
      # returns a list of item objects (events).
      for event in response.get('items', []):
        if "recurrence" in event:
          recur_req=self.service.events().instances(calendarId=cal,timeMin=strtime,eventId=event["id"],maxResults=1)
          recur_response=recur_req.execute()
          meetjson=recur_response["items"][0]
          #self.log("recurring meetjson={} check date formats".format(meetjson))
        else:
          meetjson=event
        # meetjson now holds the next calendar event
        if not meetjson["status"]=="cancelled":
          if "dateTime" in meetjson["start"]:   # datetime start keys are meetings ones with only a date are allday events
            # The event object is a dict object with a 'summary' key.
            meetings[meetjson['start']['dateTime']]=meetjson['summary']
      # Get the next request object by passing the previous request object to
      # the list_next method.
      request = self.service.events().list_next(request, response)
    self.log("meetings={}".format(meetings))
    return meetings

  # right now, we only have one light in each room to turn on, and they are named consistently
  # in the future, there should be a list of devices to turn on in response to an alarm
  # also provide method of selecting days to run alarm possibly tied into calendar...
  def alarm_lights(self,kwargs):
    room=kwargs["arg1"]
    self.log("active={}".format(self.alarms[room]["active"]))
    if self.alarms[room]["active"]=="on":
      self.turn_on("light.{}_light_switch".format(room))
      self.log("Lights should have been turned on light.{}_light_switch".format(room),level="INFO")
    else:
      self.log("Lights not scheduled for today {}= {}".format(room,self.alarms[room]),level="INFO")
    self.alarms[room]["handle"]=""

  def print_calendar(self):
    self.log("Printing Calendar")
    for room in self.alarms:
      if not self.alarms[room]["handle"]==None:
        ainfo=self.info_timer(self.alarms[room]["handle"])
        self.log("room={},alarmstate active?={}, handle {}".format(room, self.alarmstate[room]["active"],ainfo))
        self.log("{:<10}{:<10}{}".format(room,self.alarmstate[room]["active"],ainfo["info_time"]))

  def log(self,msg,level="INFO"):
    obj,fname, line, func, context, index=inspect.getouterframes(inspect.currentframe())[1]
    super(calalarm,self).log("{} - ({}) {}".format(func,str(line),msg),level)

  def info_timer(self,alarmHandle):
    rv={}
    try:
      info_time,info_interval,info_kwargs=super(calalarm,self).info_timer(alarmHandle)
      rv={"info_time":info_time,"info_interval":info_interval,"info_kwargs":info_kwargs}
      return(rv)
    except ValueError:
      self.log("error getting timer info on handle {}".format(alarmHandle))
      return(None)
    else:
      self.log("something else went boom: {}".format(sys.exc_info()[0]))
      raise

  def caldateFormat(self,indate):
    if indate.find("Z")<0:
      dateformat="%Y-%m-%dT%H:%M:%S"+self.tzoffset
    else:
      dateformat="%Y-%m-%dT%H:%M:%SZ"
    return dateformat

  ######################
  #
  # build_entity_list (self, ingroup, inlist - optional: defaults to all entity types))
  #
  # build a list of all of the entities in a group or nested hierarchy of groups
  #
  # ingroup = Starting group to cascade through
  # inlist = a list of the entity types the list may contain.  Use this if you only want a list of lights and switches for example.
  #            this would then exclude any input_booleans, input_sliders, media_players, sensors, etc. - defaults to all entity types.
  #
  # returns a python list containing all the entities found that match the device types in inlist.
  ######################
  def build_entity_list(self,ingroup,inlist=['all']):
    retlist=[]
    types=[]
    typelist=[]

    # validate values passed in
    if not self.entity_exists(ingroup):
      self.log("entity {} does not exist in home assistant".format(ingroup))
      return None
    if isinstance(inlist,list):
      typelist=inlist
    else:
      self.log("inlist must be a list ['light','switch','media_player'] for example")
      return None

    # determine what types of HA entities to return
    if "all" in typelist:
      types=["all"]
    else:
      types= types + typelist
      types.append("group")            # include group so that it doesn't ignore child groups

    # check the device type to see if it is something we care about
    devtyp, devname = self.split_entity(ingroup)
    if (devtyp in types) or ("all" in types):                # do we have a valid HA entity type
      if devtyp=="group":                                    # entity is a group so iterate through it recursing back into this function.
        for entity in self.get_state(ingroup,attribute="all")["attributes"]["entity_id"]:
          newitem=self.build_entity_list(entity,typelist)    # recurse through each member of the child group we are in.
          if not newitem==None:                              # None means there was a problem with the value passed in, so don't include it in our output list
            retlist.extend(newitem)                          # all is good so concatenate our lists together
      else:
        retlist.append(ingroup)                                      # actual entity so return it as part of a list so it can be concatenated
    return retlist

