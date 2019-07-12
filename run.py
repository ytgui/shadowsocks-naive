from multiprocessing import Process
import server_5
import client_5

if __name__ == "__main__":
    server_5.init_logging()
    p1 = Process(target=server_5.main)
    p2 = Process(target=client_5.main)
    p1.start()
    p2.start()
    p1.join()
    p2.join()
