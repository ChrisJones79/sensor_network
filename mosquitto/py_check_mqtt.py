#!/home/chris/.pyenv/versions/3.13.11/bin/python3
import time
import paho.mqtt.client as mqtt

host="192.168.40.101"; port=1883
def on_connect(c,u,f,rc,p=None):
    print("connect rc:", rc)
    c.subscribe("$SYS/broker/version", 0)
def on_message(c,u,m):
    print(m.topic, m.payload.decode(errors="ignore"))
    c.disconnect()

c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_connect=on_connect
c.on_message=on_message
c.connect(host, port, 20)
c.loop_start()
time.sleep(5)
c.loop_stop()
print("done")