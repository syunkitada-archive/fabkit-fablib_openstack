# coding: utf-8

import os
from fabkit import sudo, env, user, Package, filer, run
from fablib.python import Python
import openstack_util
from fablib.base import SimpleBase

MODE_CONTROLLER = 1
MODE_COMPUTE = 2


class Nova(SimpleBase):
    def __init__(self, mode=MODE_CONTROLLER):
        self.prefix = '/usr'
        self.python = Python(self.prefix, '2.7')
        self.usr_prefix = '/usr'
        self.usr_python = Python(self.usr_prefix, '2.7')
        self.data_key = 'nova'
        self.mode = mode
        self.data = {
            'user': 'nova',
            'debug': 'true',
            'verbose': 'true',
        }

        if mode == MODE_CONTROLLER:
            self.services = [
                'os-nova-api',
                'os-nova-cert',
                'os-nova-consoleauth',
                'os-nova-scheduler',
                'os-nova-conductor',
                'os-nova-novncproxy',
            ]

        elif mode == MODE_COMPUTE:
            self.services = [
                'libvirtd',
                'messagebus',
                'os-nova-compute',
            ]

    def init_data(self):
        self.connection = openstack_util.get_mysql_connection(self.data)
        self.data.update({
            'timeout_nbd': 1,
            'sudoers_cmd': '/usr/bin/nova-rootwrap /etc/nova/rootwrap.conf *',
            'lock_path': '/var/lock/subsys/nova',
            'my_ip': env.node['ip']['default_dev']['ip'],
            'vncserver_listen': env.node['ip']['default_dev']['ip'],
            'vncserver_proxyclient_address': env.node['ip']['default_dev']['ip'],
            'keystone': env.cluster['keystone'],
            'database': {
                'connection': self.connection['str']
            },
        })

    def setup(self):
        data = self.init()

        if self.is_package:
            user.add(data['user'], 'wheel')

            openstack_util.setup_common(self.python)
            if self.mode == MODE_CONTROLLER:
                Package('novnc').install()

            if self.mode == MODE_COMPUTE:
                Package('libvirt').install()
                Package('sysfsutils').install()
                Package('qemu-kvm').install()
                Package('libvirt-python').install()
                Package('libvirt-devel').install()
                Package('dbus').install()

                # libvirt-pythonを利用するには、ディストリビューションのものをコピーする必要がある
                # http://d.hatena.ne.jp/pyde/20130831/p1
                # site_packages = self.python.get_site_packages()
                # libvirt_python = run('rpm -ql libvirt-python | grep site-packages').split('\r\n')
                # for src in libvirt_python:
                #     sudo('ln -s {0} {1}'.format(src, site_packages))

            self.python.install('python-novaclient')

            pkg = self.python.install_from_git(
                'nova',
                'https://github.com/openstack/nova.git -b {0}'.format(data['branch']))

            filer.mkdir(data['lock_path'], owner='nova:nova')
            filer.mkdir(data['state_path'], owner='nova:nova')
            filer.mkdir(os.path.join(data['state_path'], 'instances'), owner='nova:nova')

            if not filer.exists('/etc/nova'):
                sudo('cp -r {0}/etc/nova/ /etc/nova/'.format(pkg['git_dir']))
            if not filer.exists('/usr/bin/nova'):
                sudo('ln -s {0}/bin/nova /usr/bin/'.format(self.prefix))
            if not filer.exists('/usr/bin/nova-manage'):
                sudo('ln -s {0}/bin/nova-manage /usr/bin/'.format(self.prefix))
            if not filer.exists('/usr/bin/nova-rootwrap'):
                sudo('ln -s {0}/bin/nova-rootwrap /usr/bin/'.format(self.prefix))

        if self.is_conf:
            # sudoersファイルは最後に改行入れないと、シンタックスエラーとなりsudo実行できなくなる
            # sudo: >>> /etc/sudoers.d/nova: syntax error near line 2 <<<
            # この場合は以下のコマンドでvisudoを実行し、編集する
            # $ pkexec visudo -f /etc/sudoers.d/nova
            is_updated = filer.template(
                '/etc/sudoers.d/nova',
                data=data,
                src_target='sudoers.j2',
            )

            is_updated = filer.template(
                '/etc/nova/nova.conf',
                src_target='{0}/nova.conf.j2'.format(data['version']),
                data=data,
            ) or is_updated

            filer.mkdir('/var/log/nova', owner='nova:nova')
            option = '--log-dir /var/log/nova/'

            is_updated = filer.template('/etc/systemd/system/os-nova-api.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-api',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            is_updated = filer.template('/etc/systemd/system/os-nova-cert.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-cert',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            is_updated = filer.template('/etc/systemd/system/os-nova-consoleauth.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-consoleauth',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            is_updated = filer.template('/etc/systemd/system/os-nova-scheduler.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-scheduler',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            is_updated = filer.template('/etc/systemd/system/os-nova-conductor.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-conductor',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            is_updated = filer.template('/etc/systemd/system/os-nova-novncproxy.service',
                                        '755', data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-novncproxy',
                                            'option': option,
                                            'user': self.data['user'],
                                        },
                                        src_target='systemd.service') or is_updated

            # Centos7において、
            # systemdだと nova.openstack.common.threadgroup HypervisorUnavailable: Connection
            # to the hypervisor is broken on host: localhost.localdomain とエラーがでて起動しない
            # ので、initdで行う
            is_updated = filer.template('/etc/init.d/os-nova-compute', '755',
                                        data={
                                            'prefix': self.prefix,
                                            'prog': 'nova-compute',
                                            'option': option,
                                            'user': data['user'],
                                        },
                                        src_target='initd.sh') or is_updated

            self.enable_services().start_services(pty=False)
            if is_updated:
                self.restart_services(pty=False)

        if self.is_data:
            if self.mode == MODE_CONTROLLER:
                self.db_sync()

        return 0

    def cmd(self, cmd):
        return openstack_util.client_cmd('nova {0}'.format(cmd))

    def check(self):
        self.nova_api.status()
        self.nova_cert.status()
        self.nova_consoleauth.status()
        self.nova_scheduler.status()
        self.nova_conductor.status()
        self.nova_novncproxy.status()

    def enable_nova_services(self):
        result = sudo("nova-manage service list 2>/dev/null | grep disabled | awk '{print $1,$2}'")
        services = result.split('\r\n')
        services = map(lambda s: s.split(' '), services)
        for service in services:
            sudo("nova-manage service enable --service {0} --host {1}".format(
                service[0], service[1]))

    def sync_flavors(self):
        data = self.init()

        result = self.cmd("flavor-list 2>/dev/null | grep '| ' | grep -v '| ID' | awk '{print $4}'")
        flavor_list = result.split('\r\n')
        sub_set = set(flavor_list) - set(data['flavors'].keys())
        for flavor_name in sub_set:
            if len(flavor_name) == 0:
                continue
            self.cmd("flavor-delete {0}".format(flavor_name))

        for flavor_name, flavor in data['flavors'].items():
            if flavor_name not in flavor_list:
                flavor = map(lambda f: str(f), flavor)
                options = ' '.join(flavor)
                self.cmd("flavor-create --is-public true {0} auto {1}".format(flavor_name, options))

    def db_sync(self):
        if not sorted(openstack_util.show_tables(self.connection)) == sorted([
            'agent_builds',
            'aggregate_hosts',
            'aggregate_metadata',
            'aggregates',
            'block_device_mapping',
            'bw_usage_cache',
            'cells',
            'certificates',
            'compute_nodes',
            'console_pools',
            'consoles',
            'dns_domains',
            'fixed_ips',
            'floating_ips',
            'instance_actions',
            'instance_actions_events',
            'instance_extra',  # added on juno
            'instance_faults',
            'instance_group_member',
            'instance_group_policy',
            'instance_groups',
            'instance_id_mappings',
            'instance_info_caches',
            'instance_metadata',
            'instance_system_metadata',
            'instance_type_extra_specs',
            'instance_type_projects',
            'instance_types',
            'instances',
            'iscsi_targets',
            'key_pairs',
            'migrate_version',
            'migrations',
            'networks',
            'pci_devices',
            'project_user_quotas',
            'provider_fw_rules',
            'quota_classes',
            'quota_usages',
            'quotas',
            'reservations',
            's3_images',
            'security_group_default_rules',
            'security_group_instance_association',
            'security_group_rules',
            'security_groups',
            'services',
            'shadow_agent_builds',
            'shadow_aggregate_hosts',
            'shadow_aggregate_metadata',
            'shadow_aggregates',
            'shadow_block_device_mapping',
            'shadow_bw_usage_cache',
            'shadow_cells',
            'shadow_certificates',
            'shadow_compute_nodes',
            'shadow_console_pools',
            'shadow_consoles',
            'shadow_dns_domains',
            'shadow_fixed_ips',
            'shadow_floating_ips',
            'shadow_instance_actions',
            'shadow_instance_actions_events',
            'shadow_instance_extra',
            'shadow_instance_faults',
            'shadow_instance_group_member',
            'shadow_instance_group_policy',
            'shadow_instance_groups',
            'shadow_instance_id_mappings',
            'shadow_instance_info_caches',
            'shadow_instance_metadata',
            'shadow_instance_system_metadata',
            'shadow_instance_type_extra_specs',
            'shadow_instance_type_projects',
            'shadow_instance_types',
            'shadow_instances',
            'shadow_iscsi_targets',
            'shadow_key_pairs',
            'shadow_migrate_version',
            'shadow_migrations',
            'shadow_networks',
            'shadow_pci_devices',
            'shadow_project_user_quotas',
            'shadow_provider_fw_rules',
            'shadow_quota_classes',
            'shadow_quota_usages',
            'shadow_quotas',
            'shadow_reservations',
            'shadow_s3_images',
            'shadow_security_group_default_rules',
            'shadow_security_group_instance_association',
            'shadow_security_group_rules',
            'shadow_security_groups',
            'shadow_services',
            'shadow_snapshot_id_mappings',
            'shadow_snapshots',
            'shadow_task_log',
            'shadow_virtual_interfaces',
            'shadow_volume_id_mappings',
            'shadow_volume_usage_cache',
            'shadow_volumes',
            'snapshot_id_mappings',
            'snapshots',
            'tags',
            'task_log',
            'virtual_interfaces',
            'volume_id_mappings',
            'volume_usage_cache',
            'volumes',
        ]):
            sudo('nova-manage db sync')
