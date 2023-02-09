#Tank Monitor
#created by Keith Gill 2023
#uses RPI Pico W, and ultrasonic distance sensor (JSN-SR04T)

#todo:
# put on github
# make README
#upload images and schmatic

#NB: config secrets.py based on secrets_example.py

import machine, network, secrets
import utime,time,math
import binascii
import ntptime
import umail
from machine import Pin, I2C
from umqtt.simple import MQTTClient
from machine import WDT
from hcsr04 import HCSR04

#set up our watchdog timer to 8.3 sec
wdt = WDT(timeout=8300)

#set up wlan and mqtt
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
                                                                                                                                
#to list all SSID's seen
#print (wlan.scan())                                     
wlan.connect(secrets.SSID, secrets.PASSWORD)

#pet the dog
wdt.feed()

# Wait for connect or fail
max_wait = 10
while max_wait > 0:
  if wlan.status() < 0 or wlan.status() >= 3:
    break
  max_wait -= 1
  print('waiting for connection...')
  time.sleep(1)
  #pet the dog
  wdt.feed()
# Handle connection error
if wlan.status() != 3:
    #let the watchdog timer reset the system
    time.sleep(10)
    raise RuntimeError('network connection failed')
else:
  print('connected')
  status = wlan.ifconfig()
  print( 'ip = ' + status[0] )
  
def sub_cb(topic, msg):
    print(msg)

def connect_and_subscribe():
  client = MQTTClient(secrets.CLIENT,secrets.MQTTHOST,user=secrets.MQTTUSER, password=secrets.MQTTPASS, keepalive=300, ssl=False, ssl_params={})
  client.set_callback(sub_cb)
  client.connect()
  return client

def restart_and_reconnect():
  print('Failed to connect to MQTT broker. Resetting...')
  time.sleep(2)
  machine.reset()

try:
  client = connect_and_subscribe()
except OSError as e:                                                                    
  restart_and_reconnect()

#pet the dog
wdt.feed()

#let's set up the pico to use a UTC offset and set the clock properly
ntptime.settime()
rtc = machine.RTC()
#utc_shift = -6
utc_shift = int(secrets.UTCOFFSET)
tm = utime.localtime(utime.mktime(utime.localtime()) + utc_shift*3600)
tm = tm[0:3] + (0,) + tm[3:6] + (0,)
rtc.datetime(tm)




#let's publish our HA autodiscovery stuff
#first the Config topic
config = b'homeassistant/sensor/' + secrets.PROBENAME + secrets.STATE_TOPIC + b'/config'
data = b'{"uniq_id":"' + secrets.STATE_TOPIC + b'","name":"' + secrets.STATE_TOPIC + b'","state_class":"measurement","unit_of_measurement":"%", "state_topic":"homeassistant/sensor/' + secrets.STATE_TOPIC + b'/state", "value_template":"{{ value_json.reading}}" }'
client.publish(config,data,1) #publish and set it to retain
time.sleep_ms(250)
wdt.feed()

#set up our sensor
sensor = HCSR04(trigger_pin=secrets.TRIGGER_PIN, echo_pin=secrets.ECHO_PIN, echo_timeout_us=10000)
time.sleep_ms(250)

#Do our main loop
while True:
    #in future, take multiple readings, drop smallest and hishest, and then average the rest.
    numReadings = 7
    minReading = 10000
    maxReading = 0
    totalDistance = 0
    counter = numReadings
    print("starting readings")
    while counter > 0:
        #make sure the sensor is settled
        time.sleep_ms(250)
        #take a reading
        
        distance = sensor.distance_cm() 
        print("dis " + str(counter) + ": " + str(distance))
        #new min?
        if distance < minReading:
            minReading = distance
        #newmax?
        elif distance > maxReading:
            maxReading = distance
        #add our tally    
        totalDistance += distance
        
        #print("avg: " + str(avgDistance))
        
        #decrement our counter
        counter -= 1
        
        #pet the dog
        wdt.feed()  
    #do our avg
    #NB: Using a JSN-SR04T with Working range: 25cm-4M, Working frequency: 40KHZ, Detecting angle: 70 degree.
    #so 0 = 24cm distance
    distance = ((totalDistance - minReading - maxReading) / (numReadings - 2)) - secrets.MIN_DISTANCE_TO_TOP_OF_LIQUID
    
    #A full tank is a little over 4ft or 121.92 cm if the sensor is at top of the tank (not the manhole)
    # lets say it is 5 ft above the bottom = 152.4 cm
    tankHeight = secrets.TANK_HEIGHT
    percentFullFloat = (tankHeight - distance) / tankHeight * 100
    percentFull = str(int(round(percentFullFloat,0)))
    #print(percentFull)
    print('Distance:', distance, 'cm')
    #client.publish("%s/Distance" % (secrets.CLIENT), str(distance))
    #client.publish("%s/percentFull" % (secrets.CLIENT), percentFull)

        
    #publish our readings to MQTT for HA
    #get the localtime
    year, month, day, hour, mins, secs, weekday, yearday = time.localtime()

    #publish our reading to MQTT
    state = b'homeassistant/sensor/' + secrets.STATE_TOPIC + b'/state'
    #print our timestamped msg
    print("{:02d}-{:02d}-{}T{:02d}:{:02d}:{:02d}".format(year, month, day, hour, mins, secs), state +" = "+ str(distance) + "cm - " + percentFull + "%")
    
    data = b'{"Time":"' + "{:02d}-{:02d}-{}T{:02d}:{:02d}:{:02d}".format(year, month, day, hour, mins, secs) + b'","reading":"' + percentFull + b'"}'
    #pet the dog
    wdt.feed()
    
    client.publish(state, data)  #no retain

    #pet the dog
    wdt.feed()
    SMTP_OPEN = False
    if bool(secrets.EMAIL_ALERT_FLAG):
        
        if secrets.EMAIL_THRESHOLD < percentFullFloat:
            print("sending email alert")
            smtp = umail.SMTP(secrets.EMAIL_HOST, 465, ssl=True) #  SSL port
            smtp.login(secrets.EMAIL_LOGIN_USER, secrets.EMAIL_LOGIN_PASS)
            SMTP_OPEN = True
            smtp.to(secrets.EMAIL_TO)
            smtp.write("From: " + secrets.EMAIL_FROM + "\n")
            smtp.write("To: "+ secrets.EMAIL_TO + "\n")
            smtp.write("Subject: " + secrets.CLIENT + " %s Percent Full \n\n" % percentFull)
            smtp.write("Waking up from my slumber now\n")
            smtp.write(secrets.CLIENT + " is %s percent Full\n" % percentFull)
            smtp.write("See you in a while\n")
            smtp.write("...\n")
            smtp.send()
            
            if secrets.EMAIL_SMS_FLAG == False:
                smtp.quit()
            
            time.sleep(2)
            
    if bool(secrets.EMAIL_SMS_FLAG):        
        if secrets.SMS_THRESHOLD < percentFullFloat:
            print("sending SMS alert over email")
            if SMTP_OPEN == False:
                smtp = umail.SMTP(secrets.EMAIL_HOST, 465, ssl=True) #  SSL port
                smtp.login(secrets.EMAIL_LOGIN_USER, secrets.EMAIL_LOGIN_PASS)
            smtp.to(secrets.EMAIL_SMS_TO)
            smtp.write("From: " + secrets.EMAIL_FROM + "\n")
            smtp.write("To: "+ secrets.EMAIL_TO + "\n")
            smtp.write("Subject: " + secrets.CLIENT + " %s Percent Full \n\n" % percentFull)
            smtp.write(secrets.CLIENT + " is %s percent Full\n" % percentFull)
            smtp.write("...\n")
            smtp.send()
            smtp.quit()
            
    #wait until next interval
    counter = secrets.SECONDS_BETWEEN_READINGS
    while counter > 0:
        #pet the dog
        wdt.feed()
        time.sleep(1)
        counter -= 1
    