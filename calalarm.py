#
# Alarm Clock - for HomeAssistant
#
# Written By : Chip Cox
#
# Jan 8, 2017 - Added Comments
#####
import appdaemon.appapi as appapi
import inspect
import httplib2
import sys
from datetime import datetime
from tzlocal import get_localzone

from apiclient.discovery import build
from oauth2client import tools
from oauth2client.file import Storage
from oauth2client.client import AccessTokenRefreshError
from oauth2client.client import OAuth2WebServerFlow
         
class calalarm(appapi.AppDaemon):
  
  # Created an initialization file just to mimic AD it's called from __init__
  def initialize(self):
    self.LOGLEVEL="DEBUG"
    #self.log("in initialize",level="INFO")
    # initialize variables
    self.alarms={}

    self.http = httplib2.Http()
    self.client_id = "22946252841-dsmt2h71j4as4s91npps5lbg1mge74lt.apps.googleusercontent.com"
    self.client_secret = "ONhlpv5K6tYJt1kBq0qxyagW"
    storage = Storage('/home/hass/code/appdaemon/calalarm/credentials.dat')
    self.tzoffset="-06:00"

    self.scope = 'https://www.googleapis.com/auth/calendar'       # The scope URL for read/write access to a user's calendar data
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
    self.rooms=["master","sam","charlie"]
    for room in self.rooms:
      self.alarms[room]={"active":"","handle":""}
      
    ####### Build list of rooms based on calendars assigned to room groups in HA
    self.roomowners={"chip":{"room":"master","calendar":""},
                       "susan":{"room":"master","calendar":""},
                       "sam":{"room":"sam","calendar":""},
                       "charlie":{"room":"charlie","calendar":""}}
    entity="calendar"
    c=self.loadCalendars()
    #self.log("c={}".format(c))

    for cal in c:
      #self.log("cal={}".format(c[cal]))
      if c[cal] in self.roomowners:
         self.roomowners[c[cal]]["calendar"]=cal


      # setup listeners
    teststate=self.listen_state(self.input_boolean_changed, "input_boolean")
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

    # add alarm to dictionary
  def addalarm(self,room,alarmtime):
    # schedule the alarm and add handle to the dictionary so it can be cancled if needed
    # Dictionary should be {"room":{"active":"yes/no","handle":alarmhandle},"room2":{"active":"yes/no","handle":alarmhandle}}
    self.log("Adding alarm")
    self.log("room= {} handle={}".format(room,self.alarms[room]["handle"]))
    if datetime.strptime(alarmtime,"%Y-%m-%dT%H:%M:%S"+self.tzoffset)>datetime.now():
      if not self.alarms[room]["handle"]=="":
        info_time,info_interval,info_kwargs=self.info_timer(self.alarms[room]["handle"])
        self.log("existing timer {}, interval {}, kwargs={}".format(info_time,info_interval,info_kwargs))
        if info_time>datetime.strptime(alarmtime,"%Y-%m-%dT%H:%M:%S"+self.tzoffset):
          self.log("replace alarm")
          self.cancel_timer(self.alarms[room]["handle"])
          self.alarms[room]["handle"]=self.run_at(self.alarm_lights,datetime.strptime(alarmtime,"%Y-%m-%dT%H:%M:%S"+self.tzoffset),arg1=room)
          self.log("Alarm updated for {} room to alarmtime={}".format(room,alarmtime))
        else:
          self.log("Duplicate alarm do nothing")
      else:
        self.alarms[room]["handle"]=self.run_at(self.alarm_lights,datetime.strptime(alarmtime,"%Y-%m-%dT%H:%M:%S"+self.tzoffset),arg1=room)
        self.log("new alarm added for {} room at alarmtime={}".format(room,alarmtime))
    else:
      self.log("Alarm time {} already past".format(alarmtime))

  def checkifcalchanged(self,kwargs):
    for owner in self.roomowners:
      self.schedulealarm(self.roomowners[owner]["room"])

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
        self.alarms[room]["active"]=new
        self.log("room {} active set to {}".format(room,new))
        self.schedulealarm(room)
    else:
      if room in self.rooms:
        self.alarms[room]["active"]=new                    # alarm has been deactivated
        if not self.alarms[room]["handle"]=="":            #cleanup any current alarms
          self.cancel_timer(self.alarms[room]["handle"])
          self.alarms[room]["handle"]=""

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
    return meetings

  # right now, we only have one light in each room to turn on, and they are named consistently
  # in the future, there should be a list of devices to turn on in response to an alarm
  # also provide method of selecting days to run alarm possibly tied into calendar...
  def alarm_lights(self,kwargs):
    room=kwargs["arg1"]
    if self.alarms[room]["active"]=="on":
      self.turn_on("light.{}_light_switch".format(room))
      self.log("Lights should have been turned on light.{}_light_switch".format(room),level="INFO")
    else:
      self.log("Lights not scheduled for today {}= {}".format(room,self.alarms[room][self.dow[todaydow]]),level="INFO")

  def print_calendar(self,cal):
    self.log("Printing Calendar")
    for c in cal:
      self.log("Calendar={} description={} start_time={}".format(c,cal[c]["attributes"]["description"],cal[c]["attributes"]["start_time"]))
