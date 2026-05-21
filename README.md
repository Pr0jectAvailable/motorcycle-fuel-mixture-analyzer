# Idea

I often tune motorcycles for myself and my friends, but it's not always accurate and quick. To that end, I decided to get a device based on a lambda sensor. After researching the topic, I learned that a wide-band lambda sensor is needed for acceptable tuning. After looking at prices, I realized it was out of my price range, so I decided to develop my own.

# The operating principle of the device

The device consists of a microcontroller, two mq7 sensors (carbon monoxide measurement), one mq2, AHT20+BMP280, and in the future an SD card for storing records.

The MQ2 and MQ7 sensors measure the gas flow through the cooling pipe (optimal pipe parameters will be selected) and, based on this data and engine speed, calculate the mixture state. The AHT20 and BMP280 are used to refine the parameters based on temperature and pressure. The MQ7 sensors operate alternately, as the documentation states that they can only accurately measure gases for 90 seconds after a 60-second warm-up.

![Image alt](https://github.com/Pr0jectAvailable/motorcycle-fuel-mixture-analyzer/raw/main/media/device.jpg)

To reduce the load on the controller, it only reads and writes values. All calculations are performed by a computer program.

![Image alt](https://github.com/Pr0jectAvailable/motorcycle-fuel-mixture-analyzer/raw/main/media/programm.png)

On the PC side, you can: enable demo mode, read, save, and read saved records, write values ​​directly to the computer (without microcontroller memory), view values ​​at a specific point on the graph, calibrate sensors, and some other minor functionality.

# what is the current situation

The project is still in its early stages of development, so I think I'll post all the schematics and updated code as soon as I achieve a stable and acceptable measurement.

# Media

Folder media

<!-- <video src="https://github.com/Pr0jectAvailable/motorcycle-fuel-mixture-analyzer/raw/main/media/test.mp4" width="100%" controls></video>

## First test

<video src="https://github.com/Pr0jectAvailable/motorcycle-fuel-mixture-analyzer/raw/main/media/stational.mp4" width="100%" controls></video> -->

