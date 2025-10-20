import paramiko
import threading


def ssh_connect(server_config):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if 'jumper' in server_config:
        jumper_config = server_config.pop('jumper')
        jumper = paramiko.SSHClient()
        jumper.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jumper.connect(**jumper_config, timeout=30)
        transport = jumper.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("跳板 transport 不可用")
        # open_channel 建立 direct-tcpip 到目标主机
        sock = transport.open_channel(
            "direct-tcpip",
            dest_addr=(server_config['hostname'], server_config['port']), 
            src_addr=("127.0.0.1", 0)
        )
        server_config['sock'] = sock
    ssh.connect(**server_config, timeout=30)
    return ssh


def safe_exec_command(client, command, timeout=60):
    stdin, stdout, stderr = client.exec_command(command)
    
    def read_output(out, result_holder):
        result_holder.append(out.read().decode())

    result = []
    thread = threading.Thread(target=read_output, args=(stdout, result))
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        stdout.channel.close()  # 强制关闭channel
        thread.join()
        raise TimeoutError(f"Command timed out: {command}")
    return result[0]
