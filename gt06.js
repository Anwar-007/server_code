// get more info about the protocol from:
// https://www.traccar.org/protocols/
// https://dl.dropboxusercontent.com/s/sqtkulcj51zkria/GT06_GPS_Tracker_Communication_Protocol_v1.8.1.pdf
const getCrc16 = require("./crc16")

class Gt06 {
  constructor() {
    this.msgBufferRaw = []
    this.msgBuffer = []
    this.imei = null
  }

  // if multiple message are in the buffer, it will store them in msgBuffer
  // the state of the last message will be represented in Gt06
  parse(data) {
    this.msgBufferRaw.length = 0
    const parsed = { expectsResponse: false }

    if (!checkHeader(data)) {
      throw { error: "unknown message header", msg: data }
    }

    //get all the packets from buffer as an array
    this.msgBufferRaw = sliceMsgsInBuff(data).slice()
    this.msgBufferRaw.forEach((msg, idx) => {
      switch (selectEvent(msg).number) {
        case 0x01: // login message
          Object.assign(parsed, parseLogin(msg))
          parsed.imei = parsed.imei
          parsed.expectsResponse = true
          parsed.responseMsg = createResponse(msg)
          break
        case 0x12: // location message
          Object.assign(parsed, parseLocation(msg), { imei: this.imei })
          break
        case 0x13: // status message
          Object.assign(parsed, parseStatus(msg), { imei: this.imei })
          parsed.expectsResponse = true
          parsed.responseMsg = createResponse(msg)
          break
        case 0x16: // alarm message
          Object.assign(parsed, parseAlarm(msg), { imei: this.imei })
          break
        default:
          throw {
            error: "unknown message type",
            event: selectEvent(msg),
          }
      }
      parsed.event = selectEvent(msg)
      parsed.parseTime = Date.now()
      // last message represents the obj state
      // and all go to the buffer for looped forwarding in the app
      if (idx === this.msgBufferRaw.length - 1) {
        Object.assign(this, parsed)
      }
      this.msgBuffer.push(parsed)
    })
  }

  clearMsgBuffer() {
    this.msgBuffer.length = 0
  }
}

module.exports = Gt06

function checkHeader(data) {
  const header = data.slice(0, 2)
  if (!header.equals(Buffer.from("7878", "hex"))) {
    return false
  }
  return true
}

function selectEvent(data) {
  let eventStr = "unknown"
  switch (data[3]) { //protocol number is the 4th byte
    case 0x01:
      eventStr = "login"
      break
    case 0x12:
      eventStr = "location"
      break
    case 0x13:
      eventStr = "status"
      break
    case 0x16:
      eventStr = "alarm"
      break
    default:
      eventStr = "unknown"
      break
  }
  return { number: data[3], string: eventStr }
}

function parseLogin(data) {
  return {
    imei: parseInt(data.slice(4, 12).toString("hex"), 10),
    serialNumber: data.readUInt16BE(12), //read 2 bytes starting at offset (UInt16 -> 2 bytes)
    // errorCheck: data.readUInt16BE(14)
  }
}

function parseStatus(data) {
  const statusInfo = data.slice(4, 9)
  const terminalInfo = statusInfo.slice(0, 1).readUInt8(0)
  const voltageLevel = statusInfo.slice(1, 2).readUInt8(0)
  const gsmSigStrength = statusInfo.slice(2, 3).readUInt8(0)

  const alarm = (terminalInfo & 0x38) >> 3
  let alarmType = "normal"
  switch (alarm) {
    case 1:
      alarmType = "shock"
      break
    case 2:
      alarmType = "power cut"
      break
    case 3:
      alarmType = "low battery"
      break
    case 4:
      alarmType = "sos"
      break
    default:
      alarmType = "normal"
      break
  }

  const termObj = {
    status: Boolean(terminalInfo & 0x01),
    ignition: Boolean(terminalInfo & 0x02),
    charging: Boolean(terminalInfo & 0x04),
    alarmType: alarmType,
    gpsTracking: Boolean(terminalInfo & 0x40),
    relayState: Boolean(terminalInfo & 0x80),
  }

  let voltageLevelStr = "no power (shutting down)"
  switch (voltageLevel) {
    case 1:
      voltageLevelStr = "extremely low battery"
      break
    case 2:
      voltageLevelStr = "very low battery (low battery alarm)"
      break
    case 3:
      voltageLevelStr = "low battery (can be used normally)"
      break
    case 4:
      voltageLevelStr = "medium"
      break
    case 5:
      voltageLevelStr = "high"
      break
    case 6:
      voltageLevelStr = "very high"
      break
    default:
      voltageLevelStr = "no power (shutting down)"
      break
  }

  let gsmSigStrengthStr = "no signal" // how shall it send without signal :-D
  switch (gsmSigStrength) {
    case 1:
      gsmSigStrengthStr = "extremely weak signal"
      break
    case 2:
      gsmSigStrengthStr = "very weak signal"
      break
    case 3:
      gsmSigStrengthStr = "good signal"
      break
    case 4:
      gsmSigStrengthStr = "strong signal"
      break
    default:
      gsmSigStrengthStr = "no signal"
      break
  }

  return {
    terminalInfo: termObj,
    voltageLevel: voltageLevelStr,
    gsmSigStrength: gsmSigStrengthStr,
  }
}

function parseLocation(data) {
  const datasheet = {
    startBit: data.readUInt16BE(0),
    protocolLength: data.readUInt8(2),
    protocolNumber: data.readUInt8(3),
    fixTime: data.slice(4, 10),
    quantity: data.readUInt8(10),
    lat: data.readUInt32BE(11),
    lon: data.readUInt32BE(15),
    speed: data.readUInt8(19),
    course: data.readUInt16BE(20),
    mcc: data.readUInt16BE(22),
    mnc: data.readUInt8(24),
    lac: data.readUInt16BE(25),
    cellId: parseInt(data.slice(27, 30).toString("hex"), 16),
    serialNr: data.readUInt16BE(30),
    errorCheck: data.readUInt16BE(32),
  }

  const parsed = {
    fixTime: parseDatetime(datasheet.fixTime).toISOString(),
    fixTimestamp: parseDatetime(datasheet.fixTime).getTime() / 1000,
    satCnt: (datasheet.quantity & 0xf0) >> 4, // lower 4 bits = total satellites
    satCntActive: datasheet.quantity & 0x0f, // upper 4 bits = no. of satellites used
    lat: decodeGt06Lat(datasheet.lat, datasheet.course),
    lon: decodeGt06Lon(datasheet.lon, datasheet.course),
    speed: datasheet.speed,
    speedUnit: "km/h",
    realTimeGps: Boolean(datasheet.course & 0x2000),
    gpsPositioned: Boolean(datasheet.course & 0x1000),
    eastLongitude: !Boolean(datasheet.course & 0x0800),
    northLatitude: Boolean(datasheet.course & 0x0400),
    course: datasheet.course & 0x3ff,
    mcc: datasheet.mcc,
    mnc: datasheet.mnc,
    lac: datasheet.lac,
    cellId: datasheet.cellId,
    serialNr: datasheet.serialNr,
    errorCheck: datasheet.errorCheck,
  }
  return parsed
}

// not tested! not sent by my tracker
function parseAlarm(data) {
  const datasheet = {
    startBit: data.readUInt16BE(0),
    protocolLength: data.readUInt8(2),
    protocolNumber: data.readUInt8(3),
    fixTime: data.slice(4, 10),
    quantity: data.readUInt8(10),
    lat: data.readUInt32BE(11),
    lon: data.readUInt32BE(15),
    speed: data.readUInt8(19),
    course: data.readUInt16BE(20),
    mcc: data.readUInt16BE(22),
    mnc: data.readUInt8(24),
    lac: data.readUInt16BE(25),
    cellId: parseInt(data.slice(27, 30).toString("hex"), 16),
    terminalInfo: data.readUInt8(31),
    voltageLevel: data.readUInt8(32),
    gpsSignal: data.readUInt8(33),
    alarmLang: data.readUInt16BE(34),
    serialNr: data.readUInt16BE(36),
    errorCheck: data.readUInt16BE(38),
  }

  const parsed = {
    fixTime: parseDatetime(datasheet.fixTime).toISOString(),
    fixTimestamp: parseDatetime(datasheet.fixTime).getTime() / 1000,
    satCnt: (datasheet.quantity & 0xf0) >> 4,
    satCntActive: datasheet.quantity & 0x0f,
    lat: decodeGt06Lat(datasheet.lat, datasheet.course),
    lon: decodeGt06Lon(datasheet.lon, datasheet.course),
    speed: datasheet.speed,
    speedUnit: "km/h",
    realTimeGps: Boolean(datasheet.course & 0x2000),
    gpsPositioned: Boolean(datasheet.course & 0x1000),
    eastLongitude: !Boolean(datasheet.course & 0x0800),
    northLatitude: Boolean(datasheet.course & 0x0400),
    course: datasheet.course & 0x3ff,
    mmc: datasheet.mnc,
    cellId: datasheet.cellId,
    terminalInfo: datasheet.terminalInfo,
    voltageLevel: datasheet.voltageLevel,
    gpsSignal: datasheet.gpsSignal,
    alarmLang: datasheet.alarmLang,
    serialNr: datasheet.serialNr,
    errorCheck: datasheet.errorCheck,
  }
  return parsed
}

function createResponse(data) {
  const respRaw = Buffer.from("787805FF0001d9dc0d0a", "hex")
  // we put the protocol of the received message into the response message
  // at position byte 3 (0xFF in the raw message)
  respRaw[3] = data[3]
  appendCrc16(respRaw)
  return respRaw
}

function parseDatetime(data) {
  // GT06 datetime YY MM DD hh mm ss
  // year will be like 0x0B = 11 so add 2000 -> 2011
  // JS months are 0-11 so subtract 1
  return new Date(
    Date.UTC(data[0] + 2000, data[1] - 1, data[2], data[3], data[4], data[5]),
  )
}

function decodeGt06Lat(lat, course) {
  let latitude = lat / 60.0 / 30000.0
  if (!(course & 0x0400)) {
    latitude = -latitude
  }
  return Math.round(latitude * 1000000) / 1000000
}

function decodeGt06Lon(lon, course) {
  let longitude = lon / 60.0 / 30000.0
  if (course & 0x0800) {
    longitude = -longitude
  }
  //round to 6 decimal places (22.4739888908 -> 22473988.8908) then rounded to 22473988 then divided to get og
  return Math.round(longitude * 1000000) / 1000000
}

function appendCrc16(data) {
  // write the crc16 at the 4th position from the right (2 bytes)
  // the last two bytes are the line ending
  // crc is calculated from Length to Serial Number so 2 to 6
  data.writeUInt16BE(
    getCrc16(data.slice(2, 6)).readUInt16BE(0),
    data.length - 4,
  )
}

function sliceMsgsInBuff(data) {
  const startPattern = new Buffer.from("7878", "hex") //gt06 messages always start with 7878
  let nextStart = data.indexOf(startPattern, 2)
  const msgArray = []

  //no next packet, so return with the one packet
  if (nextStart === -1) {
    msgArray.push(new Buffer.from(data))
    return msgArray
  }
  //handle multiple packets
  //push the first packet to msgArray
  //copy remaining packets to redMsgBuff
  msgArray.push(new Buffer.from(data.slice(0, nextStart)))
  let redMsgBuff = new Buffer.from(data.slice(nextStart))

  while (nextStart != -1) {
    nextStart = redMsgBuff.indexOf(startPattern, 2)
    //if only one more packet, push and return
    if (nextStart === -1) {
      msgArray.push(new Buffer.from(redMsgBuff))
      return msgArray
    }
    //push a packet to msgArray,
    //then copy the rest to redMsgBuff until all packets are done
    msgArray.push(new Buffer.from(redMsgBuff.slice(0, nextStart)))
    redMsgBuff = new Buffer.from(redMsgBuff.slice(nextStart))
  }
  return msgArray
}