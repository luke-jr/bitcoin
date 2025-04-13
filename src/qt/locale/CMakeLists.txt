# Copyright (c) 2025-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

include(ts_files.cmake)

if(NOT "${WITH_QT_VERSION}" STREQUAL "6")
  qt5_add_translation(qm_files ${ts_files})
elseif(Qt6_VERSION VERSION_GREATER_EQUAL 6.7)
  qt6_add_lrelease(TS_FILES ${ts_files} LRELEASE_TARGET bitcoinqt_lrelease OPTIONS -silent)
  add_dependencies(bitcoinqt bitcoinqt_lrelease)
else()
  qt6_add_lrelease(bitcoinqt TS_FILES ${ts_files} OPTIONS -silent)
  add_dependencies(bitcoinqt bitcoinqt_lrelease)
endif()
