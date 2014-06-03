# Set to 0 if "normal release"
%define pre_release 1

%if 0%{?pre_release}
%define release_prefix 0pre%{pre_release}.
%endif

Name:           obs-service-gbs
License:        GPL-2.0+
Group:          Development/Tools/Building
Summary:        Get sources from a repository managed with GBS
Version:        0.5
Release:        %{?release_prefix}%{?opensuse_bs:<CI_CNT>.<B_CNT>}%{!?opensuse_bs:1}
URL:            http://www.tizen.org
Source:         %{name}-%{version}.tar.bz2
Requires:       gbs-export
Requires:       git-buildpackage-common
Requires:       gbp-repocache
Requires:       obs-service-git-buildpackage-utils > 0.6
BuildRequires:  python
BuildRequires:  python-setuptools
%if 0%{?do_unittests}
BuildRequires:  python-coverage
BuildRequires:  python-mock
BuildRequires:  python-nose
BuildRequires:  gbs-export
BuildRequires:  git-buildpackage-common
BuildRequires:  gbp-repocache
BuildRequires:  obs-service-git-buildpackage-utils
%endif
BuildArch:      noarch

%description
This is a source service for openSUSE Build Service.

This source service supports getting packaging files from a git repository that
is being maintained with the GBS tool.


%prep
%setup


%build
%{__python} setup.py build
cp config/gbs config/obs-service-gbs.example.config


%if 0%{?do_unittests}
%check
%{__python} setup.py nosetests
%endif


%install
%{__python} setup.py install --skip-build --root=%{buildroot} --prefix=%{_prefix}
rm -rf %{buildroot}%{python_sitelib}/*info


%files
%defattr(-,root,root,-)
%doc COPYING DEPLOYMENT
%doc config/obs-service-gbs.example.config
%dir /usr/lib/obs
%dir /usr/lib/obs/service
/usr/lib/obs/service/*
%{python_sitelib}/obs_service_gbs
%dir %{_sysconfdir}/obs
%dir %{_sysconfdir}/obs/services
%config %{_sysconfdir}/obs/services/*
