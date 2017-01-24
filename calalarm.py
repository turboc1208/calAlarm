#
# Alarm Clock - for HomeAssistant
#
# Written By : Chip Cox
#
# Jan 8, 2017 - Added Comments
#####
import appdaemon.appapi as appapi
import datetime
import inspect
         
class calalarm(appapi.AppDaemon):
  
  # Created an initialization file just to mimic AD it's called from __init__
  def initialize(self):
      self.LOGLEVEL="DEBUG"
      self.log("in initialize",level="INFO")
      # initialize variables
      self.alarms={}
      ######  Next generate this from group in HA
      self.rooms=["master","sam","charlie"]
      for room in self.rooms:
        self.alarms[room]={"active":"","handle":""}
      
      self.log("alarms={}".format(self.alarms))

      ####### Build list of rooms based on calendars assigned to room groups in HA
      self.roomowners={"chip":{"room":"master","calendar":""},
                       "susan":{"room":"master","calendar":""},
                       "sam":{"room":"sam","calendar":""},
                       "charlie":{"room":"charlie","calendar":""}}
      entity="calendar"
      c=self.get_state("calendar")
      self.log("c={}".format(c))

      for cal in c:
        owner=c[cal]["attributes"]["friendly_name"][:c[cal]["attributes"]["friendly_name"].find(".")]
        if owner in self.roomowners:
           self.roomowners[owner]["calendar"]=c[cal]["entity_id"]

      self.log("roomowners={}".format(self.roomowners))

      # setup listeners
      teststate=self.listen_state(self.input_boolean_changed, "input_boolean")
      self.log("teststate after listen state input_boolena={}".format(teststate))
      teststate=self.listen_event(self.restartHA,"ha_started")
      self.log("teststate after listen state input_boolena={}".format(teststate))
      teststate=self.listen_state(self.calchanged,"calendar")
      self.log("teststate after listen state input_boolena={}".format(teststate))
      teststate=self.run_every(self.checkifcalchanged,datetime.datetime.now(),15*60)
      self.log("teststate after listen state input_boolena={}".format(teststate))

      # setup initial values in HA based on saved alarm settings
      for room in self.rooms:
        self.schedulealarm(room)

  def terminate(self):
    self.log("in terminate cleaning up")

  # handle HA restart
  def restartHA(self,event_name,data,kwargs):
    self.log("HA event {}".format(event_name),level="WARNING")
    # read calendar and update HA alarm time based on results.
    for owner in self.roomowners:
      meeting=self.get_state(owner["calendar"])
      if meeting["attributes"]["message"].upper()=="WAKEUP":
        self.addalarm(owner["room"],meeting["attributes"]["start_time"])

  # add alarm to dictionary
  def addalarm(self,room,alarmtime):
    # schedule the alarm and add handle to the dictionary so it can be cancled if needed
    # Dictionary should be {"room":{"active":"yes/no","handle":alarmhandle},"room2":{"active":"yes/no","handle":alarmhandle}}
    self.log("adding alarm")
    if not self.alarms[room]["handle"]=="":
      self.log("handle is of type {}".format(type(self.alarms[room]["handle"])))
      info_time,info_interval,info_kwargs=self.info_timer(self.alarms[room]["handle"])
      self.log("existing timer {}, interval {}, kwargs={}".format(info_time,info_interval,info_kwargs))
      if info_time!=datetime.datetime.strptime(alarmtime,"%Y-%m-%d %H:%M:%S"):
        self.log("replace alarm")
        self.cancel_timer(self.alarms[room]["handle"])
      else:
        self.log("Duplicate alarm")
    else:
      if datetime.datetime.strptime(alarmtime,"%Y-%m-%d %H:%M:%S")>datetime.datetime.now():
        self.alarms[room]["handle"]=self.run_at(self.alarm_lights,datetime.datetime.strptime(alarmtime,"%Y-%m-%d %H:%M:%S"))
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
    else:
      self.log("nothing really changed")
            
  # input boolean for turning the alarm on or off
  def input_boolean_changed(self, entity, attribute, old, new, kwargs):
    self.log("in handle_input_boolean")
    # input_boolean.masteralarm
    # Get room from entity name
    room=entity[entity.find(".")+1:entity.find("alarm")]
    if new=="on":
      if room in self.rooms:
        self.alarms[room]["active"]=new
        self.log("room {} active set to {}".format(room,new))
        self.schedulealarm(room)
    else:
      if not self.alarms[room]["handle"]=="":
        self.cancel_timer(self.alarms[room]["handle"])
        self.alarms[room]["handle"]=""

  def getRoomOwner(self,room):
    ownerlist=[]
    for owner in self.roomowners:
      if self.roomowners[owner]["room"]==room:
        ownerlist.append(owner)
    return ownerlist

  def schedulealarm(self,room):
    self.log("In schedulealarm - {}".format(room))
    owner=self.getRoomOwner(room)
    self.log("room={}, owner={}".format(room,owner))
    for o in owner:
      meeting=self.get_state(self.roomowners[o]["calendar"],"all")
      self.log("owner={}, room={}, meeting={}".format(o,self.roomowners[o]["room"],meeting["attributes"]["message"]))
      if meeting["attributes"]["message"].upper()=="WAKEUP":
        self.addalarm(self.roomowners[o]["room"],meeting["attributes"]["start_time"])
        self.log("alarm scheduled for {}".format(meeting["attributes"]["start_time"]))
    

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

#  # overrides appdaemon log file to handle application specific log files
#  # to use this you must set self.LOGLEVEL="DEBUG" or whatever in the initialize function
#  # although technically you could probably set it anywhere in the app if you wanted to
#  # just debug a function, although you probably want to set it back when you get done
#  # in the function or the rest of the program will start spewing messages
#  def log(self,message,level="INFO"):
#    levels = {                                          # these levels were taken from AppDaemon's files which were taken from python's log handler
#              "CRITICAL": 50,
#              "ERROR": 40,
#              "WARNING": 30,
#              "INFO": 20,
#              "DEBUG": 10,
#              "NOTSET": 0
#            }
#
#    if hasattr(self, "LOGLEVEL"):                        # if the LOGLEVEL attribute has been set then deal with whether to print or not.
#      if levels[level]>=levels[self.LOGLEVEL]:           # if the passed in level is >= to the desired LOGLevel the print it.
#        super().log("{}({}) - {} - message={}".format(inspect.stack()[1][3],inspect.stack()[1][2],level,message))
#    else:                                                # the LOGLEVEL attribute was not set so just do the log file normally
#      super().log("{}".format(message),level)

