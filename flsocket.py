import time
import json
import os
import asyncio
import websockets
from threading import Thread

from PIL import Image

import numpy as np
import torch
import torch.utils.data as data
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms

import torch
from torch import nn
from torch import optim
from torchvision.datasets.mnist import MNIST
import pdb

import syft as sy

def data_transforms():
    return transforms.Compose([
                        transforms.ToTensor(),
                        transforms.Normalize((0.1307,), (0.3081,))
                    ])

def build_datasets():
    train = datasets.MNIST('../data', train=True, download=True, transform=data_transforms())
    test = datasets.MNIST('../data', train=False, transform=data_transforms())
    return train, test

class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 20, 5, 1)
        self.conv2 = nn.Conv2d(20, 50, 5, 1)
        self.fc1 = nn.Linear(4*4*50, 500)
        self.fc2 = nn.Linear(500, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, 4*4*50)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)

def train(model, device, train_loader, optimizer, epoch):
    print('train')
    model.train()

    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        #print(data, target)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(epoch, batch_idx * len(data), len(train_loader.dataset),
            100. * batch_idx / len(train_loader), loss.item()))



def start_server():
    async def echo(websocket, path):
        async for message in websocket:
            print(f'RCV: {message}')
            time.sleep(1)
            await websocket.send(message)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    asyncio.get_event_loop().run_until_complete(websockets.serve(echo, 'localhost', 8765))
    print("Starting Federator...\n")
    asyncio.get_event_loop().run_forever()



class SocketThreader (threading.Thread):
   def __init__(self, id, participant):
      threading.Thread.__init__(self)
      self.thread_id = id
      self.participant = participant

   def run(self):
      print ("Starting " + self.thread_id)




class FederatedLearningServer:
    def __init__(self, id, connection_params, hook):
        self.port = connection_params['port']
        self.host = connection_params['host']
        self.id = id
        self.worker = sy.VirtualWorker(hook, id=id, verbose=True)
        self.current_status = 'waiting_for_clients'
        self.connected_clients = set()
        self.msg_queue = asyncio.Queue()

    def load_data(self, obj):
        self.worker.register_obj(obj)

    async def notify_state():
        if self.connected_clients:
            message = self.current_status
            await asyncio.wait([client.send(message) for client in self.connected_clients])

    async def responder(self, websocket, path):
        self.connected_clients.add(websocket)
        try:
            #await websocket.send(self.current_status)
            async for message in websocket:
                data = json.loads(message)
                if data['action'] == 'st':
                    for cl in self.connected_clients:
                        cl.send("OH HAI")
                if data['action'] == 'SIGN_UP_FOR_ROUND':
                    await self.current_status
        finally:
            pass



    async def handler(websocket, path):
        print("Got a new connection...")
        consumer_task = asyncio.ensure_future(consumer_handler(websocket))
        producer_task = asyncio.ensure_future(producer_handler(websocket))

        done, pending = await asyncio.wait([consumer_task, producer_task]
                                        , return_when=asyncio.FIRST_COMPLETED)
        print("Connection closed, canceling pending tasks")
        for task in pending:
            task.cancel()


    def start(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        asyncio.get_event_loop().run_until_complete(websockets.serve(self.responder, self.host, self.port))

        print("Starting Federator...\n")
        asyncio.get_event_loop().run_forever()


class FederatedLearningClient:
    def __init__(self, id, server_uri, hook, loop, protocol='websocket'):
        self.id = id
        self.server_uri = server_uri
        self.worker = sy.VirtualWorker(hook, id=id, verbose=True)
        self.websocket = None
        self.loop = loop
        self.msg_queue = asyncio.Queue()

    def load_data(self, obj):
        self.worker.register_obj(obj)

    def connect_to_federator(self):
        yield from websockets.connect(self.server_uri)

    async def consumer_handler(self):
        print('consumer')
        result = await self.websocket.recv()
        print(f'[{self.id}] - got {result}')

    async def producer_handler(self):
        while True:
            message = await self.msg_queue.get()
            print(f'[{self.id}] - sending {message}')
            await self.websocket.send(message)

    async def handler(self):
        consumer_task = asyncio.ensure_future(self.consumer_handler())
        producer_task = asyncio.ensure_future(self.producer_handler())
        done, pending = await asyncio.wait(
            [consumer_task, producer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    async def participate_in_round(self):
        async with websockets.connect(self.server_uri) as websocket:
            self.websocket = websocket
            websocket.send({ 'action': 'SIGN_UP_FOR_ROUND' })
            result = await websocket.recv()
            print(f'[{self.id}] - signing up. got {result}')
            await self.handler()



async def repl():
    async with websockets.connect('ws://localhost:8765') as websocket:
        while True:
            cmd = input("cmd:  ")
            await websocket.send(json.dumps({ 'action': str(cmd) }))
            resp = await websocket.recv()
            print("> {}".format(resp))


def main():
    hook = sy.TorchHook(torch)
    server = FederatedLearningServer("fed1", { 'host': 'localhost', 'port': 8765 }, hook )

    def start():
        server.start()
    thread = Thread(target=start)
    thread.start()



    train, test  = build_datasets()
    num_workers = 3
    xs = [ [] for _ in np.arange(num_workers) ]
    ys = [ [] for _ in np.arange(num_workers) ]
    for idx in np.arange(10):
        (tensor, lbl) = train[idx]
        bucket = idx % num_workers
        xs[bucket].append(tensor)
        ys[bucket].append(lbl)

    for idx in np.arange(num_workers):
        def doobab():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client = FederatedLearningClient(id=f"worker-{idx}", server_uri='ws://localhost:8765', loop=loop, hook=hook)
#            client.participate_in_round()
    #        client.connect_to_federator()
            loop.run_until_complete(client.connect_to_federator())
        thread = Thread(target=doobab)
        thread.start()

    asyncio.get_event_loop().run_until_complete(repl())

if __name__ == "__main__":
    main()
