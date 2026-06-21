# 온비드 Open API 명세

## 서비스 정보
- **서비스ID**: SVC-API-018
- **서비스명**: 온비드 공고상세 물건정보 조회서비스 (OnbidPbancCltrDtlSrvc)
- **운영URL**: `https://apis.data.go.kr/B010003/OnbidPbancCltrDtlSrvc`
- **오퍼레이션**: `getPbancCltrInf`
- **콜백URL**: `[서비스URL]/getPbancCltrInf`

## 요청 파라미터
| 영문명 | 국문명 | 크기 | 필수 | 샘플 |
|--------|--------|------|------|------|
| serviceKey | 서비스키 | 100 | 필수 | 인증키(URL-Encode) |
| pageNo | 페이지번호 | 2 | 필수 | 1 |
| numOfRows | 한 페이지 결과 수 | 5 | 필수 | 10 |
| resultType | 응답유형 | - | 필수 | json |
| pbancMngNo | 공고관리번호 | VARCHAR(40) | 필수 | 202406-21411-00 |

## 응답 필드 전체
| 영문명 | 국문명 | 타입 | 샘플 |
|--------|--------|------|------|
| resultCode | 응답코드 | VARCHAR(10) | 00 |
| resultMsg | 응답메시지 | VARCHAR(20) | NORMAL SERVICE |
| pageNo | 페이지수 | NUMBER(4) | 1 |
| totalCount | 데이터총개수 | NUMBER(5) | 1 |
| numOfRows | 한페이지결과수 | NUMBER(4) | 10 |
| pbancMngNo | 공고관리번호 | VARCHAR(40) | 202406-21411-00 |
| onbidPbancNo | 온비드공고번호 | NUMBER | - |
| pbctNo | 공매번호 | NUMBER | - |
| cltrMngNo | 물건관리번호 | VARCHAR(30) | 2025-1200-015749 |
| thmImgUrl | 썸네일이미지URL | VARCHAR(2000) | - |
| prptDivCd | 재산유형코드 | VARCHAR(20) | 0007 |
| prptDivNm | 재산유형코드명 | VARCHAR(100) | 압류재산 |
| dspsMthodCd | 처분방식코드 | VARCHAR(20) | 0001 |
| dspsMthodNm | 처분방식코드명 | VARCHAR(100) | 매각 |
| bidMthodCd | 세부입찰방식코드 | VARCHAR(20) | 0001 |
| bidMthodNm | 세부입찰방식코드명 | VARCHAR(100) | 최고가방식 |
| cltrUsgLclsCtgrId | 용도대분류코드 | VARCHAR(20) | - |
| cltrUsgMclsCtgrId | 용도중분류코드 | VARCHAR(20) | - |
| cltrUsgSclsCtgrId | 용도소분류코드 | VARCHAR(20) | 10402 |
| cltrUsgLclsCtgrNm | 용도대분류코드명 | VARCHAR(100) | 부동산 |
| cltrUsgMclsCtgrNm | 용도중분류코드명 | VARCHAR(100) | 산업용및기타특수용건물 |
| cltrUsgSclsCtgrNm | 용도소분류코드명 | VARCHAR(100) | 창고시설 |
| onbidCltrNm | 물건명 | VARCHAR(1000) | 경기도 광주시 남종면 검천리 산 93-1 임야 |
| usbdNft | 유찰횟수 | NUMBER(15) | 1 |
| batcBidYn | 일괄물건여부 | CHAR(1) | N |
| cltrAdr | 물건주소 | VARCHAR(2000) | 경기도 광주시 남종면 검천리 |
| pbctNsq | 회차 | VARCHAR(3) | 001 |
| pbctsn | 차수 | VARCHAR(5) | 001 |
| cltrBidBgngDt | 입찰시작일시 | CHAR(12) | 202406041900 |
| cltrBidEndDt | 입찰종료일시 | CHAR(12) | 202408051900 |
| apslEvlAmt | 감정평가금액 | NUMBER(22) | 302872850 |
| lowstBidPrcIndctCont | 최저입찰가격 | NUMBER(18) | 302872850 |
| apslPrcCtrsLowstBidRto | 감정가대비현재최저입찰가 | NUMBER(12,6) | 80 |
| frstCtrsLowstBidPrcRto | 최초최저입찰가대비현재 | NUMBER(12,6) | 50 |
| feeRate | 할인율 | NUMBER | 80 |
| pbctStatCd | 입찰결과구분코드 | VARCHAR(4) | 0011 |
| pbctStatNm | 입찰결과구분코드명 | VARCHAR(100) | 유찰 |
| pbancKindCd | 공고유형코드 | VARCHAR(4) | 0001 |
| pbancKindNm | 공고유형코드명 | VARCHAR(100) | 일반공고 |
| exctStatCd | 집행상태코드 | VARCHAR(4) | 0003 |
| exctStatNm | 집행상태명 | VARCHAR(100) | 개찰완료 |
