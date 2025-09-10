const net = require("node:net")

const Gt06 = require("./gt06")

const PORT = 5023

const server = net.createServer((client) => {
  console.log("gt06 connected: ", client.remoteAddress)

  const gt06 = new Gt06()
  client.on("data", (data) => {
    //console.log("recieved", data.toString("hex"))
    try {
      gt06.parse(data)
    } catch (e) {
      console.log("err", e)
      return
    }

    if (gt06.expectsResponse) {
      client.write(gt06.responseMsg)
    }

    gt06.msgBuffer.forEach((msg) => {
      console.log(msg)
    })

    gt06.clearMsgBuffer()
  })
})

server.listen(PORT, () => {
  console.log("Server started on port: ", PORT)
})
