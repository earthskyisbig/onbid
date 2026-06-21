# 온비드 API 코드표

## 재산유형코드 (prptDivCd)
| 코드 | 설명 |
|------|------|
| 0002 | 공유재산 |
| 0003 | 금융권담보재산 |
| 0004 | 불용품 |
| 0005 | 기타일반재산 |
| 0006 | 유입재산 |
| 0007 | 압류재산 |
| 0008 | 수탁재산 |
| 0010 | 국유재산 |
| 0011 | 공공개발재산 |
| 0013 | 파산재산 |

## 처분방식코드 (dspsMthodCd)
| 코드 | 설명 |
|------|------|
| 0001 | 매각 |
| 0002 | 임대 |

## 세부입찰방식코드 (bidMthodCd)
| 코드 | 설명 |
|------|------|
| 0001 | 최고가방식 |
| 0002 | 최저가방식 |
| 0003 | 전자입찰방식 |

## 입찰결과구분코드 (pbctStatCd)
| 코드 | 설명 | 투자 대응 |
|------|------|----------|
| 0001 | 입찰준비중 | 입찰 가능 — 준비 |
| 0002 | 입찰진행중 | 입찰 가능 — 즉시 검토 |
| 0003 | 입찰마감 | 입찰 불가 |
| 0006 | 개찰중 | 결과 대기 |
| 0009 | 수의계약가능 | 협의 입찰 가능 |
| 0010 | 낙찰 | 완료 |
| 0011 | 유찰 | 재공고 예정 — 관심 유지 |
| 0012 | 취소 | 진행 불가 |

## 공고유형코드 (pbancKindCd)
| 코드 | 설명 | 의미 |
|------|------|------|
| 0001 | 일반공고 | 정상 공고 |
| 0002 | 재공고 | 유찰 후 재공고 — 최저가 인하 가능 |
| 0003 | 정정공고 | 내용 수정됨 — 재확인 필요 |
| 0004 | 연기공고 | 입찰 일정 변경 |
| 0005 | 취소공고 | 공고 취소 |
| 0006 | 긴급공고 | 긴급 처분 |

## 집행상태코드 (exctStatCd)
| 코드 | 설명 |
|------|------|
| 0001 | 개찰준비중 |
| 0002 | 개찰중 |
| 0003 | 개찰완료 |

## 응답 결과코드 (resultCode)
| 코드 | 메시지 | 대응 |
|------|--------|------|
| 00 | NORMAL_CODE | 정상 처리 |
| 01 | APPLICATION_ERROR | 재시도 |
| 02 | DB_ERROR | 재시도 |
| 03 | NODATA_ERROR | 해당 공고번호 스킵 |
| 04 | HTTP_ERROR | 재시도 |
| 05 | SERVICETIMEOUT_ERROR | 30초 후 재시도 |
| 10 | INVALID_REQUEST_PARAMETER_ERROR | 파라미터 확인 |
| 11 | NO_MANDATORY_REQUEST_PARAMETERS_ERROR | 필수 파라미터 확인 |
| 12 | NO_OPENAPI_SERVICE_ERROR | 서비스 확인 |
| 20 | SERVICE_ACCESS_DENIED_ERROR | 접근 권한 확인 |
| 21 | TEMPORARILY_DISABLE_THE_SERVICEKEY_ERROR | 60초 후 재시도 |
| 22 | LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR | 요청 한도 초과, 대기 |
| 30 | SERVICE_KEY_IS_NOT_REGISTERED_ERROR | .env API키 확인 |
| 31 | DEADLINE_HAS_EXPIRED_ERROR | API키 갱신 필요 |
| 32 | UNREGISTERED_IP_ERROR | IP 등록 확인 |
| 99 | UNKNOWN_ERROR | 관리자 문의 |
