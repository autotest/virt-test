// TcpClient.cpp : Defines the entry point for the console application.
// Need add ws2_32.lib to link

#include <stdio.h>
#include <winsock.h>

int main(int argc, char* argv[])
{
	WORD wVersion;
	WSADATA wsaData;
	int err;
	wVersion = MAKEWORD(1,1);
	int DEFAULT_PORT = 12323;

	if (argc != 2){
		printf("Need server IP", FALSE);
		return 1;
	}

	err = WSAStartup(wVersion,&wsaData);
	if(err != 0){
		return 0;
	}

	SOCKET connectSocket = ::socket(AF_INET,SOCK_STREAM,0);

	sockaddr_in servAddr;
	servAddr.sin_family = AF_INET;
	servAddr.sin_addr.S_un.S_addr = inet_addr(argv[1]);
	servAddr.sin_port=htons(DEFAULT_PORT);

	if(connect(connectSocket,(struct sockaddr*)&servAddr,
	   sizeof(servAddr)) != SOCKET_ERROR){
   		::send(connectSocket,"done", 4,MSG_DONTROUTE);
	}

	closesocket(connectSocket);
	WSACleanup();

	return 0;
}

